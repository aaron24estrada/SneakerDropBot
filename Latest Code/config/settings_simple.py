"""
Simplified settings for Render.com deployment
Environment variable based configuration
"""
import os
from typing import Optional
from loguru import logger


class SimpleSettings:
    """Simplified settings using environment variables"""
    
    def __init__(self):
        # Bot configuration
        self.telegram_bot_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self.admin_telegram_chat_id: Optional[str] = os.getenv("ADMIN_TELEGRAM_CHAT_ID")
        
        # Database configuration
        self.mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_database: str = os.getenv("MONGODB_DATABASE", "sneakerdropbot")
        
        # Payment configuration
        self.stripe_publishable_key: Optional[str] = os.getenv("STRIPE_PUBLISHABLE_KEY")
        self.stripe_secret_key: Optional[str] = os.getenv("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret: Optional[str] = os.getenv("STRIPE_WEBHOOK_SECRET")
        
        # App configuration
        self.app_name: str = os.getenv("APP_NAME", "SneakerDropBot")
        self.app_version: str = os.getenv("APP_VERSION", "1.0.0")
        self.environment: str = os.getenv("ENVIRONMENT", "production")
        self.debug: bool = os.getenv("DEBUG", "false").lower() == "true"
        
        # API configuration
        self.api_host: str = os.getenv("API_HOST", "0.0.0.0")
        self.api_port: int = int(os.getenv("PORT", 8000))  # Render uses PORT
        
        # Feature flags
        self.enable_scraping: bool = os.getenv("ENABLE_SCRAPING", "false").lower() == "true"
        self.enable_premium: bool = os.getenv("ENABLE_PREMIUM", "true").lower() == "true"
        self.enable_analytics: bool = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
        
        # Rate limiting
        self.rate_limit_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
        self.max_requests_per_minute: int = int(os.getenv("MAX_REQUESTS_PER_MINUTE", 60))
        
        # Logging
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        
        # Validate critical settings
        self._validate_settings()
    
    def _validate_settings(self):
        """Validate critical settings"""
        if not self.telegram_bot_token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set - bot will not function")
        
        if not self.mongodb_uri:
            logger.warning("⚠️ MONGODB_URI not set - using default local connection")
        
        if self.enable_premium and not self.stripe_secret_key:
            logger.warning("⚠️ Premium enabled but STRIPE_SECRET_KEY not set")
        
        logger.info(f"✅ Settings loaded for environment: {self.environment}")
        logger.info(f"✅ Bot token configured: {'Yes' if self.telegram_bot_token else 'No'}")
        logger.info(f"✅ Database configured: {'Yes' if 'mongodb' in self.mongodb_uri else 'No'}")
        logger.info(f"✅ Payments configured: {'Yes' if self.stripe_secret_key else 'No'}")
    
    def get_database_url(self) -> str:
        """Get database URL"""
        return self.mongodb_uri
    
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"
    
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.environment.lower() in ["development", "dev", "local"]
    
    def get_bot_webhook_url(self) -> Optional[str]:
        """Get bot webhook URL"""
        base_url = os.getenv("RENDER_EXTERNAL_URL")
        if base_url:
            return f"{base_url}/webhook/telegram"
        return None
    
    def export_for_render(self) -> dict:
        """Export settings for Render deployment"""
        return {
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token or "REQUIRED",
            "MONGODB_URI": self.mongodb_uri,
            "MONGODB_DATABASE": self.mongodb_database,
            "STRIPE_SECRET_KEY": self.stripe_secret_key or "OPTIONAL",
            "STRIPE_PUBLISHABLE_KEY": self.stripe_publishable_key or "OPTIONAL",
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "INFO",
            "ENABLE_SCRAPING": "false",  # Disabled for Render free tier
            "ENABLE_PREMIUM": "true",
            "ENABLE_ANALYTICS": "true"
        }
