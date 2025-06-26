"""
Simplified database connection for Render.com deployment
Basic MongoDB operations without heavy dependencies
"""
from typing import Optional, Dict, Any
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from loguru import logger
import os


class SimpleDatabaseManager:
    """Simplified database manager for basic operations"""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.database_name = os.getenv("MONGODB_DATABASE", "sneakerdropbot")
    
    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(self.mongodb_uri)
            self.db = self.client[self.database_name]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("✅ Connected to MongoDB successfully")
            
            # Create basic indexes
            await self._create_basic_indexes()
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("✅ Disconnected from MongoDB")
    
    async def _create_basic_indexes(self):
        """Create basic database indexes"""
        try:
            # Users collection indexes
            await self.db.users.create_index("telegram_id", unique=True)
            await self.db.users.create_index("created_at")
            
            # Tracked sneakers indexes
            await self.db.tracked_sneakers.create_index([
                ("user_id", 1),
                ("sneaker_name", 1)
            ])
            
            # Alerts indexes
            await self.db.alerts.create_index("user_id")
            await self.db.alerts.create_index("created_at")
            
            logger.info("✅ Database indexes created")
            
        except Exception as e:
            logger.warning(f"⚠️ Index creation failed: {e}")
    
    async def health_check(self) -> bool:
        """Check database health"""
        try:
            await self.client.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"❌ Database health check failed: {e}")
            return False
    
    async def get_basic_stats(self) -> Dict[str, Any]:
        """Get basic statistics"""
        try:
            stats = {
                "total_users": await self.db.users.count_documents({}),
                "premium_users": await self.db.users.count_documents({"is_premium": True}),
                "tracked_sneakers": await self.db.tracked_sneakers.count_documents({}),
                "alerts_sent_today": await self._get_alerts_today(),
                "last_updated": datetime.utcnow().isoformat()
            }
            return stats
        except Exception as e:
            logger.error(f"❌ Failed to get stats: {e}")
            return {
                "error": str(e),
                "last_updated": datetime.utcnow().isoformat()
            }
    
    async def _get_alerts_today(self) -> int:
        """Get alerts sent today"""
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            return await self.db.alerts.count_documents({
                "created_at": {"$gte": today_start}
            })
        except:
            return 0
    
    # User operations
    async def get_or_create_user(self, telegram_id: int, username: str = None) -> Dict[str, Any]:
        """Get or create a user"""
        try:
            user = await self.db.users.find_one({"telegram_id": telegram_id})
            
            if not user:
                user_data = {
                    "telegram_id": telegram_id,
                    "username": username,
                    "is_premium": False,
                    "created_at": datetime.utcnow(),
                    "last_active": datetime.utcnow(),
                    "tracked_count": 0,
                    "alerts_received": 0
                }
                
                result = await self.db.users.insert_one(user_data)
                user_data["_id"] = result.inserted_id
                return user_data
            else:
                # Update last active
                await self.db.users.update_one(
                    {"telegram_id": telegram_id},
                    {"$set": {"last_active": datetime.utcnow()}}
                )
                return user
                
        except Exception as e:
            logger.error(f"❌ User operation failed: {e}")
            # Return a default user object
            return {
                "telegram_id": telegram_id,
                "username": username,
                "is_premium": False,
                "created_at": datetime.utcnow(),
                "tracked_count": 0,
                "alerts_received": 0
            }
    
    async def update_user_premium_status(self, telegram_id: int, is_premium: bool) -> bool:
        """Update user premium status"""
        try:
            result = await self.db.users.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"is_premium": is_premium, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ Premium status update failed: {e}")
            return False
    
    # Tracking operations
    async def add_tracked_sneaker(self, user_id: int, sneaker_data: Dict[str, Any]) -> bool:
        """Add a tracked sneaker"""
        try:
            tracking_data = {
                "user_id": user_id,
                "sneaker_name": sneaker_data.get("name"),
                "size": sneaker_data.get("size"),
                "price_limit": sneaker_data.get("price_limit"),
                "created_at": datetime.utcnow(),
                "is_active": True,
                "alerts_sent": 0
            }
            
            await self.db.tracked_sneakers.insert_one(tracking_data)
            
            # Update user's tracked count
            await self.db.users.update_one(
                {"telegram_id": user_id},
                {"$inc": {"tracked_count": 1}}
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Add tracked sneaker failed: {e}")
            return False
    
    async def get_user_tracked_sneakers(self, user_id: int) -> list:
        """Get user's tracked sneakers"""
        try:
            cursor = self.db.tracked_sneakers.find({
                "user_id": user_id,
                "is_active": True
            }).sort("created_at", -1)
            
            tracked = []
            async for item in cursor:
                tracked.append(item)
            
            return tracked
            
        except Exception as e:
            logger.error(f"❌ Get tracked sneakers failed: {e}")
            return []
    
    # Alert operations
    async def log_alert(self, alert_data: Dict[str, Any]) -> bool:
        """Log an alert"""
        try:
            alert_record = {
                "user_id": alert_data.get("user_id"),
                "sneaker_name": alert_data.get("sneaker_name"),
                "alert_type": alert_data.get("type", "restock"),
                "message": alert_data.get("message"),
                "retailer": alert_data.get("retailer"),
                "price": alert_data.get("price"),
                "created_at": datetime.utcnow(),
                "delivered": True
            }
            
            await self.db.alerts.insert_one(alert_record)
            
            # Update user's alert count
            await self.db.users.update_one(
                {"telegram_id": alert_data.get("user_id")},
                {"$inc": {"alerts_received": 1}}
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Log alert failed: {e}")
            return False
    
    # Analytics operations
    async def update_daily_analytics(self, **metrics) -> None:
        """Update daily analytics"""
        try:
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            await self.db.analytics.update_one(
                {"date": today},
                {"$inc": metrics, "$set": {"updated_at": datetime.utcnow()}},
                upsert=True
            )
            
        except Exception as e:
            logger.error(f"❌ Analytics update failed: {e}")
