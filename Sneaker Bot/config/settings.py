"""
Configuration settings for SneakerDropBot
"""
import os
from typing import List, Optional
from pydantic import BaseSettings, validator
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    app_name: str = "SneakerDropBot"
    debug: bool = False
    environment: str = "production"
    
    # Database
    mongodb_url: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    database_name: str = os.getenv("DATABASE_NAME", "sneakerdropbot")
    
    # Telegram Bot
    telegram_bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_webhook_url: Optional[str] = os.getenv("TELEGRAM_WEBHOOK_URL")
    
    # Admin Users
    admin_ids: List[int] = []
    
    @validator("admin_ids", pre=True)
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(id_.strip()) for id_ in v.split(",") if id_.strip()]
        return v or []
    
    # Stripe Payment
    stripe_secret_key: Optional[str] = os.getenv("STRIPE_SECRET_KEY")
    stripe_publishable_key: Optional[str] = os.getenv("STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: Optional[str] = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    # API Keys for Scrapers
    nike_api_key: Optional[str] = os.getenv("NIKE_API_KEY")
    adidas_api_key: Optional[str] = os.getenv("ADIDAS_API_KEY")
    footlocker_api_key: Optional[str] = os.getenv("FOOTLOCKER_API_KEY")
    stockx_api_key: Optional[str] = os.getenv("STOCKX_API_KEY")
    goat_api_key: Optional[str] = os.getenv("GOAT_API_KEY")
    
    # Affiliate Codes
    nike_affiliate_code: str = os.getenv("NIKE_AFFILIATE_CODE", "sneakerdropbot")
    adidas_affiliate_code: str = os.getenv("ADIDAS_AFFILIATE_CODE", "sneakerdropbot")
    footlocker_affiliate_code: str = os.getenv("FOOTLOCKER_AFFILIATE_CODE", "SDB123")
    finishline_affiliate_code: str = os.getenv("FINISHLINE_AFFILIATE_CODE", "SDBOT")
    stockx_affiliate_code: str = os.getenv("STOCKX_AFFILIATE_CODE", "sneakerdropbot")
    goat_affiliate_code: str = os.getenv("GOAT_AFFILIATE_CODE", "sneakerdropbot")
    
    # Rakuten Partners
    ebay_rakuten_code: str = os.getenv("EBAY_RAKUTEN_CODE", "123456")
    eastbay_rakuten_code: str = os.getenv("EASTBAY_RAKUTEN_CODE", "789012")
    
    # Monitoring Settings
    monitoring_interval: int = int(os.getenv("MONITORING_INTERVAL", "300"))  # 5 minutes
    scraping_interval: int = int(os.getenv("SCRAPING_INTERVAL", "600"))     # 10 minutes
    alert_cooldown: int = int(os.getenv("ALERT_COOLDOWN", "300"))           # 5 minutes
    
    # Rate Limiting
    requests_per_minute: int = int(os.getenv("REQUESTS_PER_MINUTE", "60"))
    concurrent_requests: int = int(os.getenv("CONCURRENT_REQUESTS", "10"))
    
    # Alert Limits
    free_alerts_per_day: int = int(os.getenv("FREE_ALERTS_PER_DAY", "5"))
    premium_alerts_per_day: int = int(os.getenv("PREMIUM_ALERTS_PER_DAY", "1000"))
    
    # Pricing
    monthly_price: int = int(os.getenv("MONTHLY_PRICE", "999"))  # $9.99 in cents
    yearly_price: int = int(os.getenv("YEARLY_PRICE", "9999"))   # $99.99 in cents
    
    # External URLs
    webhook_url: str = os.getenv("WEBHOOK_URL", "https://api.sneakerdropbot.com")
    frontend_url: str = os.getenv("FRONTEND_URL", "https://sneakerdropbot.com")
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = os.getenv("LOG_FILE", "logs/sneakerdropbot.log")
    
    # Redis (optional for caching)
    redis_url: Optional[str] = os.getenv("REDIS_URL")
    cache_ttl: int = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes
    
    # Proxy Settings (for scraping)
    proxy_enabled: bool = os.getenv("PROXY_ENABLED", "false").lower() == "true"
    proxy_urls: List[str] = []
    
    @validator("proxy_urls", pre=True)
    def parse_proxy_urls(cls, v):
        if isinstance(v, str):
            return [url.strip() for url in v.split(",") if url.strip()]
        return v or []
    
    # Browser Settings
    headless_browser: bool = os.getenv("HEADLESS_BROWSER", "true").lower() == "true"
    browser_timeout: int = int(os.getenv("BROWSER_TIMEOUT", "30"))
    
    # Feature Flags
    enable_resell_tracking: bool = os.getenv("ENABLE_RESELL_TRACKING", "true").lower() == "true"
    enable_price_history: bool = os.getenv("ENABLE_PRICE_HISTORY", "true").lower() == "true"
    enable_flip_analysis: bool = os.getenv("ENABLE_FLIP_ANALYSIS", "true").lower() == "true"
    enable_early_access: bool = os.getenv("ENABLE_EARLY_ACCESS", "true").lower() == "true"
    
    # API Rate Limits per Retailer
    nike_rate_limit: int = int(os.getenv("NIKE_RATE_LIMIT", "30"))
    adidas_rate_limit: int = int(os.getenv("ADIDAS_RATE_LIMIT", "30"))
    footlocker_rate_limit: int = int(os.getenv("FOOTLOCKER_RATE_LIMIT", "20"))
    stockx_rate_limit: int = int(os.getenv("STOCKX_RATE_LIMIT", "15"))
    goat_rate_limit: int = int(os.getenv("GOAT_RATE_LIMIT", "15"))
    
    # Retry Settings
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))
    
    # Data Retention
    data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))
    log_retention_days: int = int(os.getenv("LOG_RETENTION_DAYS", "30"))
    
    # Notification Settings
    enable_push_notifications: bool = os.getenv("ENABLE_PUSH_NOTIFICATIONS", "true").lower() == "true"
    enable_email_notifications: bool = os.getenv("ENABLE_EMAIL_NOTIFICATIONS", "false").lower() == "true"
    
    # Email Settings (if enabled)
    smtp_host: Optional[str] = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: Optional[str] = os.getenv("SMTP_USERNAME")
    smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD")
    from_email: str = os.getenv("FROM_EMAIL", "noreply@sneakerdropbot.com")
    
    # Security
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-change-this")
    jwt_algorithm: str = "HS256"
    jwt_expiration: int = int(os.getenv("JWT_EXPIRATION", "86400"))  # 24 hours
    
    # Analytics
    enable_analytics: bool = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
    google_analytics_id: Optional[str] = os.getenv("GOOGLE_ANALYTICS_ID")
    
    # Performance Tuning
    max_workers: int = int(os.getenv("MAX_WORKERS", "4"))
    batch_size: int = int(os.getenv("BATCH_SIZE", "10"))
    connection_pool_size: int = int(os.getenv("CONNECTION_POOL_SIZE", "20"))
    
    # Development Settings
    mock_scrapers: bool = os.getenv("MOCK_SCRAPERS", "false").lower() == "true"
    mock_payments: bool = os.getenv("MOCK_PAYMENTS", "false").lower() == "true"
    test_mode: bool = os.getenv("TEST_MODE", "false").lower() == "true"
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
        # Environment variable mappings
        fields = {
            "admin_ids": {"env": "ADMIN_IDS"},
            "proxy_urls": {"env": "PROXY_URLS"}
        }
    
    def get_database_url(self) -> str:
        """Get complete database URL"""
        return f"{self.mongodb_url}/{self.database_name}"
    
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"
    
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment.lower() in ["development", "dev"]
    
    def get_retailer_rate_limit(self, retailer: str) -> int:
        """Get rate limit for specific retailer"""
        rate_limits = {
            "nike": self.nike_rate_limit,
            "adidas": self.adidas_rate_limit,
            "footlocker": self.footlocker_rate_limit,
            "stockx": self.stockx_rate_limit,
            "goat": self.goat_rate_limit
        }
        return rate_limits.get(retailer.lower(), 30)  # Default 30 requests/minute
    
    def get_affiliate_code(self, retailer: str) -> str:
        """Get affiliate code for retailer"""
        codes = {
            "nike": self.nike_affiliate_code,
            "adidas": self.adidas_affiliate_code,
            "footlocker": self.footlocker_affiliate_code,
            "finishline": self.finishline_affiliate_code,
            "stockx": self.stockx_affiliate_code,
            "goat": self.goat_affiliate_code
        }
        return codes.get(retailer.lower(), "sneakerdropbot")
    
    def get_api_key(self, service: str) -> Optional[str]:
        """Get API key for service"""
        keys = {
            "nike": self.nike_api_key,
            "adidas": self.adidas_api_key,
            "footlocker": self.footlocker_api_key,
            "stockx": self.stockx_api_key,
            "goat": self.goat_api_key
        }
        return keys.get(service.lower())
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Check if feature is enabled"""
        features = {
            "resell_tracking": self.enable_resell_tracking,
            "price_history": self.enable_price_history,
            "flip_analysis": self.enable_flip_analysis,
            "early_access": self.enable_early_access,
            "push_notifications": self.enable_push_notifications,
            "email_notifications": self.enable_email_notifications,
            "analytics": self.enable_analytics
        }
        return features.get(feature.lower(), False)
    
    def get_scraping_config(self) -> dict:
        """Get scraping configuration"""
        return {
            "interval": self.scraping_interval,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "concurrent_requests": self.concurrent_requests,
            "headless_browser": self.headless_browser,
            "browser_timeout": self.browser_timeout,
            "proxy_enabled": self.proxy_enabled,
            "proxy_urls": self.proxy_urls
        }
    
    def get_alert_config(self) -> dict:
        """Get alert configuration"""
        return {
            "cooldown": self.alert_cooldown,
            "free_daily_limit": self.free_alerts_per_day,
            "premium_daily_limit": self.premium_alerts_per_day,
            "enable_push": self.enable_push_notifications,
            "enable_email": self.enable_email_notifications
        }
    
    def get_payment_config(self) -> dict:
        """Get payment configuration"""
        return {
            "monthly_price": self.monthly_price,
            "yearly_price": self.yearly_price,
            "stripe_public_key": self.stripe_publishable_key,
            "mock_payments": self.mock_payments
        }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export settings instance
settings = get_settings()
