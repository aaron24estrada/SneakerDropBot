"""
Real-time monitoring engine for sneaker alerts
"""
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from database.connection import db_manager
from database.models import Alert, AlertType
from scrapers.scraper_manager import scraper_manager
from utils.helpers import generate_affiliate_link
from app.bot import bot


class MonitoringEngine:
    """Real-time monitoring engine for sneaker alerts"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.alert_queue = asyncio.Queue()
        
    async def start(self):
        """Start the monitoring engine"""
        if self.is_running:
            logger.warning("Monitoring engine is already running")
            return
        
        logger.info("Starting monitoring engine...")
        
        # Schedule main monitoring job
        self.scheduler.add_job(
            self.monitor_sneakers,
            trigger=IntervalTrigger(minutes=10),  # Run every 10 minutes
            id="monitor_sneakers",
            max_instances=1,
            replace_existing=True
        )
        
        # Schedule resell data collection
        self.scheduler.add_job(
            self.collect_resell_data,
            trigger=IntervalTrigger(hours=2),  # Run every 2 hours
            id="collect_resell_data",
            max_instances=1,
            replace_existing=True
        )
        
        # Schedule daily analytics update
        self.scheduler.add_job(
            self.update_daily_analytics,
            trigger=CronTrigger(hour=0, minute=0),  # Run at midnight
            id="daily_analytics",
            max_instances=1,
            replace_existing=True
        )
        
        # Schedule health checks
        self.scheduler.add_job(
            self.health_check,
            trigger=IntervalTrigger(hours=1),  # Run every hour
            id="health_check",
            max_instances=1,
            replace_existing=True
        )
        
        # Start scheduler
        self.scheduler.start()
        
        # Start alert processing worker
        asyncio.create_task(self.process_alerts())
        
        self.is_running = True
        logger.info("Monitoring engine started successfully")
    
    async def stop(self):
        """Stop the monitoring engine"""
        if not self.is_running:
            return
        
        logger.info("Stopping monitoring engine...")
        
        self.scheduler.shutdown()
        self.is_running = False
        
        logger.info("Monitoring engine stopped")
    
    async def monitor_sneakers(self):
        """Main monitoring job - check all tracked sneakers"""
        logger.info("Starting sneaker monitoring cycle")
        
        try:
            # Get alerts from scraper manager
            alerts = await scraper_manager.monitor_tracked_sneakers()
            
            if alerts:
                logger.info(f"Generated {len(alerts)} alerts")
                
                # Add alerts to processing queue
                for alert_data in alerts:
                    await self.alert_queue.put(alert_data)
            else:
                logger.debug("No alerts generated in this cycle")
        
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
    
    async def collect_resell_data(self):
        """Collect resell market data"""
        logger.info("Starting resell data collection")
        
        try:
            # Get actively tracked sneaker keywords
            tracked_keywords = await self._get_tracked_keywords()
            
            if tracked_keywords:
                # Use scraper manager to collect real resell data
                resell_data = await scraper_manager.collect_resell_data(tracked_keywords)
                logger.info(f"Collected {len(resell_data)} resell data points")
            else:
                # Fallback to mock data if no tracked sneakers
                await self._generate_mock_resell_data()
            
            logger.info("Resell data collection completed")
        
        except Exception as e:
            logger.error(f"Error collecting resell data: {e}")
    
    async def _get_tracked_keywords(self) -> List[str]:
        """Get list of actively tracked sneaker keywords"""
        keywords = []
        
        try:
            # Get unique keywords from tracked sneakers
            pipeline = [
                {"$match": {"is_active": True}},
                {"$group": {"_id": "$keyword"}},
                {"$limit": 50}  # Limit to top 50 to avoid overwhelming APIs
            ]
            
            cursor = db_manager.db.tracked_sneakers.aggregate(pipeline)
            
            async for item in cursor:
                keywords.append(item["_id"])
        
        except Exception as e:
            logger.error(f"Failed to get tracked keywords: {e}")
        
        return keywords
    
    async def _generate_mock_resell_data(self):
        """Generate mock resell data for testing"""
        from database.models import ResellData, SneakerSize
        import random
        
        # Popular sneakers for mock data
        sneakers = [
            "Jordan 4 Bred",
            "Jordan 1 Chicago",
            "Yeezy 350 Cream",
            "Yeezy 350 Zebra",
            "Air Max 90 Infrared",
            "Dunk Low Panda"
        ]
        
        platforms = ["stockx", "goat", "stadium_goods"]
        sizes = [8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12]
        
        # Generate 10 random resell data points
        for _ in range(10):
            sneaker = random.choice(sneakers)
            platform = random.choice(platforms)
            size = random.choice(sizes)
            
            # Generate realistic price based on sneaker
            base_prices = {
                "Jordan 4 Bred": 350,
                "Jordan 1 Chicago": 400,
                "Yeezy 350 Cream": 280,
                "Yeezy 350 Zebra": 320,
                "Air Max 90 Infrared": 150,
                "Dunk Low Panda": 120
            }
            
            base_price = base_prices.get(sneaker, 200)
            variation = random.uniform(0.8, 1.2)
            price = base_price * variation
            
            resell_data = ResellData(
                sneaker_name=sneaker,
                size=SneakerSize(us_size=size),
                platform=platform,
                price=price,
                last_sale_date=datetime.utcnow() - timedelta(
                    hours=random.randint(1, 72)
                )
            )
            
            await db_manager.add_resell_data(resell_data)
    
    async def update_daily_analytics(self):
        """Update daily analytics"""
        logger.info("Updating daily analytics")
        
        try:
            # Count total users
            total_users = await db_manager.db.users.count_documents({})
            
            # Count premium users
            premium_users = await db_manager.db.users.count_documents({
                "tier": "premium",
                "$or": [
                    {"subscription_expires_at": None},
                    {"subscription_expires_at": {"$gt": datetime.utcnow()}}
                ]
            })
            
            # Count alerts sent today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            alerts_today = await db_manager.db.alerts.count_documents({
                "sent_at": {"$gte": today_start}
            })
            
            # Count new signups today
            new_signups = await db_manager.db.users.count_documents({
                "created_at": {"$gte": today_start}
            })
            
            # Calculate revenue (simplified - would need actual payment data)
            revenue = premium_users * 9.99  # Simplified calculation
            
            # Update analytics
            await db_manager.update_daily_analytics(
                total_users=total_users,
                premium_users=premium_users,
                alerts_sent=alerts_today,
                new_signups=new_signups,
                revenue=revenue
            )
            
            logger.info(f"Analytics updated - Users: {total_users}, Premium: {premium_users}, Alerts: {alerts_today}")
        
        except Exception as e:
            logger.error(f"Error updating analytics: {e}")
    
    async def health_check(self):
        """Perform health checks on all components"""
        logger.info("Performing health checks")
        
        try:
            # Check scraper health
            scraper_health = await scraper_manager.health_check_all_scrapers()
            
            # Check database health
            db_health = await self._check_database_health()
            
            # Check bot health
            bot_health = await self._check_bot_health()
            
            # Log health status
            total_scrapers = len(scraper_health)
            healthy_scrapers = sum(1 for status in scraper_health.values() if status)
            
            logger.info(f"Health check - DB: {'✓' if db_health else '✗'}, "
                       f"Bot: {'✓' if bot_health else '✗'}, "
                       f"Scrapers: {healthy_scrapers}/{total_scrapers}")
            
            # Alert admins if critical systems are down
            if not db_health or not bot_health or healthy_scrapers < total_scrapers // 2:
                await self._alert_admins_health_issue(db_health, bot_health, scraper_health)
        
        except Exception as e:
            logger.error(f"Error in health check: {e}")
    
    async def _check_database_health(self) -> bool:
        """Check database connectivity"""
        try:
            await db_manager.client.admin.command('ping')
            return True
        except Exception:
            return False
    
    async def _check_bot_health(self) -> bool:
        """Check bot connectivity"""
        try:
            if bot.application and bot.application.bot:
                await bot.application.bot.get_me()
                return True
        except Exception:
            pass
        
        return False
    
    async def _alert_admins_health_issue(self, db_health: bool, bot_health: bool, scraper_health: Dict[str, bool]):
        """Alert admins about health issues"""
        from config.settings import settings
        
        issues = []
        if not db_health:
            issues.append("❌ Database connection failed")
        if not bot_health:
            issues.append("❌ Bot connection failed")
        
        for scraper, status in scraper_health.items():
            if not status:
                issues.append(f"❌ {scraper.title()} scraper failed")
        
        if issues:
            message = "🚨 **SneakerDropBot Health Alert**\n\n" + "\n".join(issues)
            
            # Send to admin users
            for admin_id in settings.admin_telegram_ids:
                try:
                    await bot.application.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send health alert to admin {admin_id}: {e}")
    
    async def process_alerts(self):
        """Process alerts from the queue"""
        logger.info("Starting alert processing worker")
        
        while True:
            try:
                # Get alert from queue (wait if empty)
                alert_data = await self.alert_queue.get()
                
                # Process the alert
                await self._send_alert(alert_data)
                
                # Mark task as done
                self.alert_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing alert: {e}")
    
    async def _send_alert(self, alert_data: Dict[str, Any]):
        """Send an alert to a user"""
        try:
            user_id = alert_data["user_telegram_id"]
            message = alert_data["message"]
            product = alert_data["product"]
            
            # Check if user can receive alerts
            user = await db_manager.get_user(user_id)
            if not user or not user.can_send_alert():
                logger.info(f"User {user_id} cannot receive alerts (limit reached)")
                return
            
            # Generate affiliate link if available
            buy_link = generate_affiliate_link(product.url, product.retailer)
            
            # Add buy button to message
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = [
                [InlineKeyboardButton("🛒 Buy Now", url=buy_link)],
                [InlineKeyboardButton("📊 Check Market", callback_data=f"market_{product.id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send the alert
            await bot.application.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="Markdown",
                reply_markup=reply_markup,
                disable_web_page_preview=False
            )
            
            # Save alert to database
            alert = Alert(
                user_telegram_id=user_id,
                tracked_sneaker_id=alert_data["tracked_sneaker_id"],
                product_id=product.id,
                alert_type=AlertType(alert_data["type"]),
                message=message
            )
            
            await db_manager.create_alert(alert)
            
            logger.info(f"Sent {alert_data['type']} alert to user {user_id} for {product.name}")
            
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    async def add_manual_alert(self, alert_data: Dict[str, Any]):
        """Add a manual alert to the queue (for admin use)"""
        await self.alert_queue.put(alert_data)
        logger.info("Manual alert added to queue")
    
    def get_status(self) -> Dict[str, Any]:
        """Get monitoring engine status"""
        return {
            "is_running": self.is_running,
            "scheduled_jobs": len(self.scheduler.get_jobs()) if self.scheduler else 0,
            "queued_alerts": self.alert_queue.qsize(),
            "next_monitoring_run": None  # TODO: Get next scheduled run time
        }


# Global monitoring engine instance
monitoring_engine = MonitoringEngine()
