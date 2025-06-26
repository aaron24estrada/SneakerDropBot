"""
Database models for SneakerDropBot
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    """Custom ObjectId type for Pydantic"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")
        return field_schema


class UserTier(str, Enum):
    """User subscription tiers"""
    FREE = "free"
    PREMIUM = "premium"


class AlertType(str, Enum):
    """Types of alerts"""
    RESTOCK = "restock"
    PRICE_DROP = "price_drop"
    FLIP_OPPORTUNITY = "flip_opportunity"


class SneakerSize(BaseModel):
    """Sneaker size model"""
    us_size: Optional[float] = None
    uk_size: Optional[float] = None
    eu_size: Optional[float] = None
    is_all_sizes: bool = False


class TrackedSneaker(BaseModel):
    """Model for tracked sneakers"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_telegram_id: int
    keyword: str
    sizes: List[SneakerSize] = []
    max_price: Optional[float] = None
    alert_types: List[AlertType] = [AlertType.RESTOCK]
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class User(BaseModel):
    """User model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    telegram_id: int = Field(unique=True)
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tier: UserTier = UserTier.FREE
    subscription_expires_at: Optional[datetime] = None
    alerts_sent_this_month: int = 0
    alerts_reset_date: datetime = Field(default_factory=lambda: datetime.utcnow().replace(day=1))
    tracked_sneakers: List[PyObjectId] = []
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_interaction: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

    def is_premium(self) -> bool:
        """Check if user has active premium subscription"""
        if self.tier == UserTier.PREMIUM:
            if self.subscription_expires_at is None:
                return True
            return datetime.utcnow() < self.subscription_expires_at
        return False

    def can_send_alert(self, max_free_alerts: int = 5) -> bool:
        """Check if user can receive more alerts this month"""
        if self.is_premium():
            return True
        
        # Reset monthly counter if needed
        current_month = datetime.utcnow().replace(day=1)
        if self.alerts_reset_date < current_month:
            self.alerts_sent_this_month = 0
            self.alerts_reset_date = current_month
            
        return self.alerts_sent_this_month < max_free_alerts

    def can_track_more_sneakers(self, max_free_tracked: int = 1) -> bool:
        """Check if user can track more sneakers"""
        if self.is_premium():
            return True
        return len(self.tracked_sneakers) < max_free_tracked


class Retailer(str, Enum):
    """Supported retailers"""
    NIKE = "nike"
    ADIDAS = "adidas"
    FOOTLOCKER = "footlocker"
    FINISH_LINE = "finish_line"
    STOCKX = "stockx"
    GOAT = "goat"
    STADIUM_GOODS = "stadium_goods"


class SneakerProduct(BaseModel):
    """Sneaker product model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    name: str
    brand: str
    model: str
    colorway: str
    sku: str
    retailer: Retailer
    url: str
    image_url: Optional[str] = None
    price: Optional[float] = None
    sizes_available: List[SneakerSize] = []
    is_in_stock: bool = False
    last_checked: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Alert(BaseModel):
    """Alert model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_telegram_id: int
    tracked_sneaker_id: PyObjectId
    product_id: PyObjectId
    alert_type: AlertType
    message: str
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    clicked: bool = False
    clicked_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ResellData(BaseModel):
    """Resell market data"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    sneaker_name: str
    size: SneakerSize
    platform: str  # stockx, goat, etc.
    price: float
    last_sale_date: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Payment(BaseModel):
    """Payment model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_telegram_id: int
    stripe_payment_intent_id: str
    amount: float
    currency: str = "usd"
    tier: UserTier
    duration_months: int = 1
    status: str  # succeeded, pending, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Analytics(BaseModel):
    """Analytics model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    date: datetime = Field(default_factory=lambda: datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0))
    total_users: int = 0
    premium_users: int = 0
    alerts_sent: int = 0
    new_signups: int = 0
    affiliate_clicks: int = 0
    revenue: float = 0.0

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ScraperHealthMetrics(BaseModel):
    """Scraper health metrics model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    retailer: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str  # healthy, warning, critical, down
    success_rate: float
    total_requests: int
    successful_requests: int
    consecutive_failures: int
    response_time_avg: float
    issues: List[str] = []
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ScraperPerformanceMetrics(BaseModel):
    """Individual scraper performance record"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    retailer: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    success: bool
    response_time: float
    error: Optional[str] = None
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class HealthAlert(BaseModel):
    """Health alert model"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    retailer: str
    alert_type: str
    severity: str  # warning, critical, down
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = {}
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
