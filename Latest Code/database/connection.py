"""
Database connection and operations
"""
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from loguru import logger

from config.settings import settings
from database.models import (
    User, TrackedSneaker, SneakerProduct, Alert, ResellData, 
    Payment, Analytics, UserTier, AlertType, Retailer,
    ScraperHealthMetrics, ScraperPerformanceMetrics, HealthAlert
)


class DatabaseManager:
    """Database manager for MongoDB operations"""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        
    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(settings.mongodb_uri)
            self.db = self.client[settings.mongodb_database]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("Connected to MongoDB successfully")
            
            # Create indexes
            await self._create_indexes()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    async def _create_indexes(self):
        """Create database indexes"""
        try:
            # Users collection indexes
            await self.db.users.create_index("telegram_id", unique=True)
            await self.db.users.create_index("tier")
            await self.db.users.create_index("subscription_expires_at")
            
            # Tracked sneakers collection indexes
            await self.db.tracked_sneakers.create_index([
                ("user_telegram_id", 1),
                ("keyword", 1),
                ("is_active", 1)
            ])
            
            # Products collection indexes
            await self.db.products.create_index([
                ("name", "text"),
                ("brand", "text"),
                ("model", "text"),
                ("colorway", "text")
            ])
            await self.db.products.create_index("sku", unique=True)
            await self.db.products.create_index("retailer")
            await self.db.products.create_index("last_checked")
            
            # Alerts collection indexes
            await self.db.alerts.create_index("user_telegram_id")
            await self.db.alerts.create_index("sent_at")
            
            # Resell data collection indexes
            await self.db.resell_data.create_index([
                ("sneaker_name", 1),
                ("platform", 1),
                ("created_at", -1)
            ])
            
            logger.info("Database indexes created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
    
    # User operations
    async def create_user(self, telegram_id: int, username: str = None, 
                         first_name: str = None, last_name: str = None) -> User:
        """Create a new user"""
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        
        try:
            result = await self.db.users.insert_one(user.dict(by_alias=True))
            user.id = result.inserted_id
            logger.info(f"Created user {telegram_id}")
            return user
        except DuplicateKeyError:
            logger.warning(f"User {telegram_id} already exists")
            return await self.get_user(telegram_id)
    
    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Get user by telegram ID"""
        user_data = await self.db.users.find_one({"telegram_id": telegram_id})
        if user_data:
            return User(**user_data)
        return None
    
    async def update_user(self, telegram_id: int, update_data: Dict[str, Any]) -> bool:
        """Update user data"""
        update_data["updated_at"] = datetime.utcnow()
        result = await self.db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    async def upgrade_user_to_premium(self, telegram_id: int, months: int = 1) -> bool:
        """Upgrade user to premium"""
        expires_at = datetime.utcnow() + timedelta(days=30 * months)
        return await self.update_user(telegram_id, {
            "tier": UserTier.PREMIUM,
            "subscription_expires_at": expires_at
        })
    
    # Tracked sneakers operations
    async def add_tracked_sneaker(self, tracked_sneaker: TrackedSneaker) -> TrackedSneaker:
        """Add a tracked sneaker"""
        result = await self.db.tracked_sneakers.insert_one(tracked_sneaker.dict(by_alias=True))
        tracked_sneaker.id = result.inserted_id
        
        # Add to user's tracked sneakers list
        await self.db.users.update_one(
            {"telegram_id": tracked_sneaker.user_telegram_id},
            {"$push": {"tracked_sneakers": tracked_sneaker.id}}
        )
        
        logger.info(f"Added tracked sneaker for user {tracked_sneaker.user_telegram_id}")
        return tracked_sneaker
    
    async def get_user_tracked_sneakers(self, telegram_id: int) -> List[TrackedSneaker]:
        """Get all tracked sneakers for a user"""
        cursor = self.db.tracked_sneakers.find({
            "user_telegram_id": telegram_id,
            "is_active": True
        })
        
        sneakers = []
        async for sneaker_data in cursor:
            sneakers.append(TrackedSneaker(**sneaker_data))
        
        return sneakers
    
    async def remove_tracked_sneaker(self, telegram_id: int, sneaker_id: str) -> bool:
        """Remove a tracked sneaker"""
        result = await self.db.tracked_sneakers.update_one(
            {"_id": sneaker_id, "user_telegram_id": telegram_id},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        
        if result.modified_count > 0:
            # Remove from user's tracked sneakers list
            await self.db.users.update_one(
                {"telegram_id": telegram_id},
                {"$pull": {"tracked_sneakers": sneaker_id}}
            )
            return True
        
        return False
    
    # Product operations
    async def upsert_product(self, product: SneakerProduct) -> SneakerProduct:
        """Insert or update a product"""
        product.last_checked = datetime.utcnow()
        
        result = await self.db.products.find_one_and_update(
            {"sku": product.sku, "retailer": product.retailer},
            {"$set": product.dict(by_alias=True, exclude={"id"})},
            upsert=True,
            return_document=True
        )
        
        return SneakerProduct(**result)
    
    async def find_matching_products(self, keyword: str, retailer: Optional[Retailer] = None) -> List[SneakerProduct]:
        """Find products matching keyword"""
        query = {"$text": {"$search": keyword}}
        if retailer:
            query["retailer"] = retailer
            
        cursor = self.db.products.find(query)
        
        products = []
        async for product_data in cursor:
            products.append(SneakerProduct(**product_data))
        
        return products
    
    # Alert operations
    async def create_alert(self, alert: Alert) -> Alert:
        """Create a new alert"""
        result = await self.db.alerts.insert_one(alert.dict(by_alias=True))
        alert.id = result.inserted_id
        
        # Increment user's alert count
        await self.db.users.update_one(
            {"telegram_id": alert.user_telegram_id},
            {"$inc": {"alerts_sent_this_month": 1}}
        )
        
        return alert
    
    async def get_user_alerts(self, telegram_id: int, limit: int = 50) -> List[Alert]:
        """Get recent alerts for a user"""
        cursor = self.db.alerts.find(
            {"user_telegram_id": telegram_id}
        ).sort("sent_at", -1).limit(limit)
        
        alerts = []
        async for alert_data in cursor:
            alerts.append(Alert(**alert_data))
        
        return alerts
    
    # Resell data operations
    async def add_resell_data(self, resell_data: ResellData) -> ResellData:
        """Add resell market data"""
        result = await self.db.resell_data.insert_one(resell_data.dict(by_alias=True))
        resell_data.id = result.inserted_id
        return resell_data
    
    async def get_resell_data(self, sneaker_name: str, limit: int = 10) -> List[ResellData]:
        """Get recent resell data for a sneaker"""
        cursor = self.db.resell_data.find(
            {"sneaker_name": {"$regex": sneaker_name, "$options": "i"}}
        ).sort("created_at", -1).limit(limit)
        
        data = []
        async for resell_item in cursor:
            data.append(ResellData(**resell_item))
        
        return data
    
    # Payment operations
    async def create_payment(self, payment: Payment) -> Payment:
        """Create a payment record"""
        result = await self.db.payments.insert_one(payment.dict(by_alias=True))
        payment.id = result.inserted_id
        return payment
    
    async def update_payment_status(self, stripe_payment_intent_id: str, status: str) -> bool:
        """Update payment status"""
        result = await self.db.payments.update_one(
            {"stripe_payment_intent_id": stripe_payment_intent_id},
            {"$set": {"status": status, "processed_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    # Analytics operations
    async def update_daily_analytics(self, **metrics) -> None:
        """Update daily analytics"""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        await self.db.analytics.update_one(
            {"date": today},
            {"$inc": metrics},
            upsert=True
        )
    
    async def get_analytics(self, days: int = 30) -> List[Analytics]:
        """Get analytics for the last N days"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        cursor = self.db.analytics.find(
            {"date": {"$gte": start_date}}
        ).sort("date", -1)
        
        analytics = []
        async for analytics_data in cursor:
            analytics.append(Analytics(**analytics_data))
        
        return analytics
    
    # === HEALTH MONITORING OPERATIONS ===
    
    async def store_health_metrics(self, metrics: Dict[str, Any]) -> None:
        """Store scraper health metrics"""
        try:
            health_metrics = ScraperHealthMetrics(**metrics)
            await self.db.scraper_health_metrics.insert_one(health_metrics.dict(by_alias=True))
        except Exception as e:
            logger.error(f"Failed to store health metrics: {e}")
    
    async def store_scraper_metrics(self, metrics: Dict[str, Any]) -> None:
        """Store individual scraper performance metrics"""
        try:
            performance_metrics = ScraperPerformanceMetrics(**metrics)
            await self.db.scraper_performance_metrics.insert_one(performance_metrics.dict(by_alias=True))
        except Exception as e:
            logger.error(f"Failed to store scraper metrics: {e}")
    
    async def store_health_alert(self, alert_data: Dict[str, Any]) -> None:
        """Store health alert"""
        try:
            alert = HealthAlert(**alert_data)
            await self.db.health_alerts.insert_one(alert.dict(by_alias=True))
        except Exception as e:
            logger.error(f"Failed to store health alert: {e}")
    
    async def get_recent_health_metrics(self, retailer: str = None, hours: int = 24) -> List[ScraperHealthMetrics]:
        """Get recent health metrics"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            query = {"timestamp": {"$gte": cutoff_time}}
            
            if retailer:
                query["retailer"] = retailer
            
            cursor = self.db.scraper_health_metrics.find(query).sort("timestamp", -1)
            
            metrics = []
            async for metric_data in cursor:
                metrics.append(ScraperHealthMetrics(**metric_data))
            
            return metrics
        except Exception as e:
            logger.error(f"Failed to get health metrics: {e}")
            return []
    
    async def get_recent_performance_metrics(self, retailer: str = None, hours: int = 24) -> List[ScraperPerformanceMetrics]:
        """Get recent performance metrics"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            query = {"timestamp": {"$gte": cutoff_time}}
            
            if retailer:
                query["retailer"] = retailer
            
            cursor = self.db.scraper_performance_metrics.find(query).sort("timestamp", -1)
            
            metrics = []
            async for metric_data in cursor:
                metrics.append(ScraperPerformanceMetrics(**metric_data))
            
            return metrics
        except Exception as e:
            logger.error(f"Failed to get performance metrics: {e}")
            return []
    
    async def get_health_alerts(self, retailer: str = None, acknowledged: bool = None, hours: int = 24) -> List[HealthAlert]:
        """Get health alerts"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            query = {"timestamp": {"$gte": cutoff_time}}
            
            if retailer:
                query["retailer"] = retailer
            if acknowledged is not None:
                query["acknowledged"] = acknowledged
            
            cursor = self.db.health_alerts.find(query).sort("timestamp", -1)
            
            alerts = []
            async for alert_data in cursor:
                alerts.append(HealthAlert(**alert_data))
            
            return alerts
        except Exception as e:
            logger.error(f"Failed to get health alerts: {e}")
            return []
    
    async def acknowledge_health_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        """Acknowledge a health alert"""
        try:
            from bson import ObjectId
            result = await self.db.health_alerts.update_one(
                {"_id": ObjectId(alert_id)},
                {
                    "$set": {
                        "acknowledged": True,
                        "acknowledged_by": acknowledged_by,
                        "acknowledged_at": datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to acknowledge health alert: {e}")
            return False
    
    async def get_scraper_success_rates(self, hours: int = 24) -> Dict[str, float]:
        """Get success rates for all scrapers"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff_time}}},
                {
                    "$group": {
                        "_id": "$retailer",
                        "total": {"$sum": 1},
                        "successful": {"$sum": {"$cond": ["$success", 1, 0]}}
                    }
                },
                {
                    "$project": {
                        "retailer": "$_id",
                        "success_rate": {"$divide": ["$successful", "$total"]}
                    }
                }
            ]
            
            cursor = self.db.scraper_performance_metrics.aggregate(pipeline)
            
            success_rates = {}
            async for result in cursor:
                success_rates[result["retailer"]] = result["success_rate"]
            
            return success_rates
        except Exception as e:
            logger.error(f"Failed to get success rates: {e}")
            return {}
    
    async def cleanup_old_health_data(self, days_to_keep: int = 30) -> None:
        """Clean up old health monitoring data"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days_to_keep)
            
            # Clean up old health metrics
            health_result = await self.db.scraper_health_metrics.delete_many(
                {"timestamp": {"$lt": cutoff_time}}
            )
            
            # Clean up old performance metrics
            perf_result = await self.db.scraper_performance_metrics.delete_many(
                {"timestamp": {"$lt": cutoff_time}}
            )
            
            # Clean up old alerts (keep acknowledged ones longer)
            alert_cutoff = datetime.utcnow() - timedelta(days=days_to_keep * 2)
            alert_result = await self.db.health_alerts.delete_many(
                {
                    "timestamp": {"$lt": alert_cutoff},
                    "acknowledged": True
                }
            )
            
            logger.info(f"Cleaned up health data: {health_result.deleted_count} health metrics, "
                       f"{perf_result.deleted_count} performance metrics, "
                       f"{alert_result.deleted_count} old alerts")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old health data: {e}")


# Global database manager instance
db_manager = DatabaseManager()


async def init_database():
    """Initialize database connection"""
    await db_manager.connect()


async def close_database():
    """Close database connection"""
    await db_manager.disconnect()
