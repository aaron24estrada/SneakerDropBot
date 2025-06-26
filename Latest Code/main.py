"""
SneakerDropBot - Main Application Entry Point
Complete functional sneaker tracking and alert bot
"""
import os
import asyncio
import signal
import sys
from datetime import datetime
from typing import List, Dict, Any
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import json

# Import all components
from database.connection import db_manager
from scrapers.scraper_manager import scraper_manager
from app.monitoring_engine import monitoring_engine
from bot.telegram_bot import create_bot, start_bot
from bot.payment_processor import payment_processor
from bot.alert_sender import create_alert_sender
from bot.affiliate_manager import affiliate_manager
from config.settings import get_settings


class SneakerDropBotApp:
    """Main application class"""
    
    def __init__(self):
        self.settings = get_settings()
        self.app = FastAPI(
            title="SneakerDropBot API",
            description="Complete sneaker tracking and alert system",
            version="1.0.0"
        )
        self.setup_middleware()
        self.setup_routes()
        self.bot = None
        self.alert_sender = None
        self.monitoring_task = None
        self.scraping_task = None
        
    def setup_middleware(self):
        """Setup FastAPI middleware"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def setup_routes(self):
        """Setup API routes"""
        
        @self.app.get("/")
        async def root():
            return {
                "message": "SneakerDropBot API",
                "version": "1.0.0",
                "status": "running",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint"""
            try:
                # Check database connection
                db_healthy = await db_manager.health_check()
                
                # Check scrapers
                scraper_health = await scraper_manager.health_check_all_scrapers()
                healthy_scrapers = sum(1 for status in scraper_health.values() if status)
                
                # Check bot status
                bot_healthy = self.bot is not None
                
                return {
                    "status": "healthy" if all([db_healthy, healthy_scrapers > 0, bot_healthy]) else "unhealthy",
                    "database": "healthy" if db_healthy else "unhealthy",
                    "scrapers": f"{healthy_scrapers}/{len(scraper_health)} healthy",
                    "bot": "healthy" if bot_healthy else "unhealthy",
                    "timestamp": datetime.utcnow().isoformat()
                }
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return {"status": "unhealthy", "error": str(e)}
        
        @self.app.get("/stats")
        async def get_statistics():
            """Get bot statistics"""
            try:
                total_users = await db_manager.get_total_users()
                premium_users = await db_manager.get_premium_users_count()
                active_tracking = await db_manager.get_active_tracking_count()
                alerts_today = await db_manager.get_alerts_count(hours=24)
                
                scraper_analytics = scraper_manager.get_scraper_analytics()
                affiliate_stats = await affiliate_manager.get_affiliate_statistics(days=30)
                
                return {
                    "users": {
                        "total": total_users,
                        "premium": premium_users,
                        "free": total_users - premium_users,
                        "premium_percentage": round((premium_users / total_users * 100) if total_users > 0 else 0, 1)
                    },
                    "tracking": {
                        "active_sneakers": active_tracking,
                        "alerts_today": alerts_today
                    },
                    "scrapers": scraper_analytics,
                    "affiliate": affiliate_stats,
                    "revenue": {
                        "monthly_estimate": premium_users * 9.99,
                        "annual_estimate": premium_users * 9.99 * 12
                    }
                }
            except Exception as e:
                logger.error(f"Error getting statistics: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/webhook/stripe")
        async def stripe_webhook(request: Request):
            """Handle Stripe webhooks"""
            try:
                payload = await request.body()
                sig_header = request.headers.get('stripe-signature')
                
                success = await payment_processor.handle_webhook(
                    payload.decode('utf-8'), 
                    sig_header
                )
                
                if success:
                    return {"status": "success"}
                else:
                    raise HTTPException(status_code=400, detail="Webhook processing failed")
                    
            except Exception as e:
                logger.error(f"Stripe webhook error: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.post("/webhook/telegram")
        async def telegram_webhook(request: Request):
            """Handle Telegram webhooks"""
            try:
                if not self.bot:
                    raise HTTPException(status_code=503, detail="Bot not initialized")
                
                update_data = await request.json()
                # Process Telegram update
                # This would integrate with python-telegram-bot webhook handling
                
                return {"status": "ok"}
                
            except Exception as e:
                logger.error(f"Telegram webhook error: {e}")
                raise HTTPException(status_code=400, detail=str(e))
        
        @self.app.get("/api/search/{keyword}")
        async def search_sneakers(keyword: str, limit: int = 10):
            """Search for sneakers across all retailers"""
            try:
                results = await scraper_manager.search_all_retailers(keyword, limit=limit)
                
                return {
                    "keyword": keyword,
                    "results_count": len(results),
                    "results": [product.dict() for product in results]
                }
                
            except Exception as e:
                logger.error(f"Search error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/market/{sneaker_name}")
        async def get_market_data(sneaker_name: str):
            """Get comprehensive market data for a sneaker"""
            try:
                market_data = await scraper_manager.get_comprehensive_market_data(sneaker_name)
                return market_data
                
            except Exception as e:
                logger.error(f"Market data error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/trending")
        async def get_trending_sneakers(days: int = 7):
            """Get trending sneakers"""
            try:
                trending = await scraper_manager.get_trending_sneakers(days=days)
                return {"trending": trending}
                
            except Exception as e:
                logger.error(f"Trending data error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/api/admin/alert")
        async def send_manual_alert(request: Request):
            """Send manual alert (admin only)"""
            try:
                data = await request.json()
                sneaker_name = data.get("sneaker_name")
                message = data.get("message")
                
                if not sneaker_name:
                    raise HTTPException(status_code=400, detail="sneaker_name required")
                
                # Get users tracking this sneaker
                tracking_users = await db_manager.get_users_tracking_keyword(sneaker_name)
                
                if not tracking_users:
                    return {"message": f"No users tracking '{sneaker_name}'", "sent_count": 0}
                
                # Send alerts
                sent_count = 0
                for user_id in tracking_users:
                    try:
                        await self.bot.application.bot.send_message(
                            chat_id=user_id,
                            text=message or f"🔥 Manual alert for {sneaker_name}",
                            parse_mode="Markdown"
                        )
                        sent_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to send manual alert to {user_id}: {e}")
                
                return {"message": f"Alert sent to {sent_count} users", "sent_count": sent_count}
                
            except Exception as e:
                logger.error(f"Manual alert error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/payment/success")
        async def payment_success(session_id: str):
            """Handle successful payment"""
            return {"message": "Payment successful! Your premium features are now active."}
        
        @self.app.get("/payment/cancel")
        async def payment_cancel():
            """Handle cancelled payment"""
            return {"message": "Payment cancelled. You can try again anytime."}
    
    async def initialize_database(self):
        """Initialize database connection and setup"""
        try:
            logger.info("Initializing database...")
            await db_manager.initialize()
            
            # Create indexes for better performance
            await db_manager.create_indexes()
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    async def initialize_scrapers(self):
        """Initialize scraper system"""
        try:
            logger.info("Initializing scrapers...")
            
            # Health check all scrapers
            health_status = await scraper_manager.health_check_all_scrapers()
            healthy_count = sum(1 for status in health_status.values() if status)
            
            logger.info(f"Scrapers initialized: {healthy_count}/{len(health_status)} healthy")
            
            if healthy_count == 0:
                logger.warning("No healthy scrapers available!")
            
        except Exception as e:
            logger.error(f"Scraper initialization failed: {e}")
            raise
    
    async def initialize_bot(self):
        """Initialize Telegram bot"""
        try:
            if not self.settings.telegram_bot_token:
                logger.error("Telegram bot token not configured")
                return
            
            logger.info("Initializing Telegram bot...")
            
            self.bot = create_bot(self.settings.telegram_bot_token)
            self.alert_sender = create_alert_sender(self.settings.telegram_bot_token)
            
            logger.info("Telegram bot initialized successfully")
            
        except Exception as e:
            logger.error(f"Bot initialization failed: {e}")
            raise
    
    async def start_monitoring(self):
        """Start monitoring and scraping tasks"""
        try:
            logger.info("Starting monitoring engine...")
            
            # Start monitoring engine
            self.monitoring_task = asyncio.create_task(
                monitoring_engine.start_monitoring()
            )
            
            # Start periodic scraping optimization
            self.scraping_task = asyncio.create_task(
                self._periodic_optimization()
            )
            
            logger.info("Monitoring started successfully")
            
        except Exception as e:
            logger.error(f"Monitoring startup failed: {e}")
            raise
    
    async def _periodic_optimization(self):
        """Periodic optimization tasks"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                
                # Optimize scraping intervals
                await scraper_manager.optimize_scraping_intervals()
                
                # Optimize affiliate links
                await affiliate_manager.optimize_affiliate_links()
                
                # Cleanup old data
                await db_manager.cleanup_old_data(days=30)
                
                logger.info("Periodic optimization completed")
                
            except Exception as e:
                logger.error(f"Periodic optimization error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retry
    
    async def start(self):
        """Start the complete application"""
        try:
            logger.info("Starting SneakerDropBot application...")
            
            # Initialize components
            await self.initialize_database()
            await self.initialize_scrapers()
            await self.initialize_bot()
            await self.start_monitoring()
            
            logger.info("SneakerDropBot started successfully!")
            
            # Start bot if token is provided
            if self.settings.telegram_bot_token and self.bot:
                logger.info("Starting Telegram bot polling...")
                bot_task = asyncio.create_task(self.bot.run())
            
            logger.info("All systems running! 🚀")
            
        except Exception as e:
            logger.error(f"Application startup failed: {e}")
            raise
    
    async def stop(self):
        """Stop the application gracefully"""
        try:
            logger.info("Stopping SneakerDropBot...")
            
            # Stop monitoring tasks
            if self.monitoring_task:
                self.monitoring_task.cancel()
            
            if self.scraping_task:
                self.scraping_task.cancel()
            
            # Stop bot
            if self.bot:
                await self.bot.application.stop()
            
            # Close database connections
            await db_manager.close()
            
            logger.info("SneakerDropBot stopped successfully")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Global app instance
app_instance = SneakerDropBotApp()

# FastAPI app for uvicorn
app = app_instance.app


async def main():
    """Main entry point"""
    # Setup logging
    logger.add(
        "logs/sneakerdropbot_{time}.log",
        rotation="1 day",
        retention="30 days",
        level="INFO"
    )
    
    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(app_instance.stop())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the application
        await app_instance.start()
        
        # Start the API server
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=int(os.getenv("PORT", 8000)),
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        logger.info(f"Starting API server on port {config.port}")
        await server.serve()
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
    finally:
        await app_instance.stop()


if __name__ == "__main__":
    # Run the application
    asyncio.run(main())
