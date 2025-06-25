"""
Advanced scraper configuration with robust monitoring settings
"""
from typing import Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class ScrapingStrategy(Enum):
    """Scraping strategy options"""
    AGGRESSIVE = "aggressive"      # Try all methods, fast scraping
    BALANCED = "balanced"          # Default - balance speed and stealth  
    STEALTH = "stealth"           # Slow, careful scraping with delays
    CONSERVATIVE = "conservative"  # Only most reliable methods


@dataclass
class RetailerConfig:
    """Configuration for individual retailer"""
    enabled: bool = True
    scraping_interval_minutes: int = 10
    max_concurrent_requests: int = 3
    request_delay_range: tuple = (1.0, 3.0)  # Random delay between requests
    strategy: ScrapingStrategy = ScrapingStrategy.BALANCED
    priority: int = 1  # 1=highest, 10=lowest
    
    # Health monitoring thresholds
    success_rate_warning: float = 0.7
    success_rate_critical: float = 0.5
    consecutive_failures_warning: int = 5
    consecutive_failures_critical: int = 10
    
    # Custom headers/settings
    custom_headers: Dict[str, str] = None
    use_proxy: bool = False
    proxy_rotation: bool = False


class ScraperConfiguration:
    """Master scraper configuration"""
    
    def __init__(self):
        # Global settings
        self.global_enabled = True
        self.health_monitoring_enabled = True
        self.auto_healing_enabled = True
        self.circuit_breaker_enabled = True
        
        # Performance settings
        self.default_timeout = 30
        self.max_retries = 3
        self.backoff_multiplier = 2.0
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 300  # 5 minutes
        
        # Health monitoring settings
        self.health_check_interval = 300  # 5 minutes
        self.performance_metrics_retention_days = 30
        self.alert_cooldown_minutes = 15
        self.auto_heal_interval = 600  # 10 minutes
        
        # Stealth settings
        self.user_agent_rotation = True
        self.ip_rotation = False  # Requires proxy setup
        self.request_fingerprint_randomization = True
        
        # Fallback strategies
        self.fallback_to_mock_data = True
        self.emergency_throttling = True
        self.adaptive_intervals = True
        
        # Per-retailer configurations
        self.retailers = {
            "nike": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=5,  # High priority
                max_concurrent_requests=2,
                strategy=ScrapingStrategy.BALANCED,
                priority=1,
                request_delay_range=(2.0, 4.0)  # Nike is strict
            ),
            "adidas": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=6,
                max_concurrent_requests=2,
                strategy=ScrapingStrategy.BALANCED,
                priority=1,
                request_delay_range=(1.5, 3.5)
            ),
            "stockx": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=8,
                max_concurrent_requests=3,
                strategy=ScrapingStrategy.AGGRESSIVE,  # StockX has good APIs
                priority=1,
                request_delay_range=(1.0, 2.0)
            ),
            "goat": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=8,
                max_concurrent_requests=3,
                strategy=ScrapingStrategy.BALANCED,
                priority=1,
                request_delay_range=(1.0, 2.5)
            ),
            "footlocker": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=10,
                max_concurrent_requests=2,
                strategy=ScrapingStrategy.STEALTH,
                priority=2,
                request_delay_range=(3.0, 6.0)
            ),
            "finish_line": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=12,
                max_concurrent_requests=2,
                strategy=ScrapingStrategy.STEALTH,
                priority=3,
                request_delay_range=(3.0, 5.0)
            ),
            "jd_sports": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=15,
                max_concurrent_requests=1,
                strategy=ScrapingStrategy.CONSERVATIVE,
                priority=3,
                request_delay_range=(4.0, 7.0)
            ),
            "champs": RetailerConfig(
                enabled=True,
                scraping_interval_minutes=15,
                max_concurrent_requests=1,
                strategy=ScrapingStrategy.CONSERVATIVE,
                priority=3,
                request_delay_range=(4.0, 7.0)
            )
        }
        
        # Strategy-specific settings
        self.strategy_settings = {
            ScrapingStrategy.AGGRESSIVE: {
                "try_all_methods": True,
                "parallel_parsing": True,
                "quick_timeout": 15,
                "max_fallbacks": 5
            },
            ScrapingStrategy.BALANCED: {
                "try_all_methods": True,
                "parallel_parsing": False,
                "quick_timeout": 20,
                "max_fallbacks": 3
            },
            ScrapingStrategy.STEALTH: {
                "try_all_methods": False,
                "parallel_parsing": False,
                "quick_timeout": 30,
                "max_fallbacks": 2,
                "extra_delays": True,
                "human_like_behavior": True
            },
            ScrapingStrategy.CONSERVATIVE: {
                "try_all_methods": False,
                "parallel_parsing": False,
                "quick_timeout": 45,
                "max_fallbacks": 1,
                "only_reliable_methods": True
            }
        }
        
        # Emergency response settings
        self.emergency_thresholds = {
            "global_failure_rate": 0.3,  # If <30% success across all scrapers
            "retailer_down_count": 3,     # If 3+ retailers are down
            "consecutive_global_failures": 10
        }
        
        # Notification settings
        self.notifications = {
            "telegram_alerts": True,
            "email_alerts": False,
            "webhook_alerts": False,
            "slack_alerts": False
        }
        
        # Data quality settings
        self.data_quality = {
            "min_confidence_score": 0.3,
            "require_price_validation": True,
            "require_name_validation": True,
            "allow_partial_data": True,
            "cross_validate_prices": True
        }
    
    def get_retailer_config(self, retailer: str) -> RetailerConfig:
        """Get configuration for specific retailer"""
        return self.retailers.get(retailer.lower(), RetailerConfig())
    
    def get_strategy_settings(self, strategy: ScrapingStrategy) -> Dict[str, Any]:
        """Get settings for specific strategy"""
        return self.strategy_settings.get(strategy, self.strategy_settings[ScrapingStrategy.BALANCED])
    
    def is_retailer_enabled(self, retailer: str) -> bool:
        """Check if retailer is enabled"""
        config = self.get_retailer_config(retailer)
        return self.global_enabled and config.enabled
    
    def get_scraping_interval(self, retailer: str) -> int:
        """Get scraping interval for retailer"""
        config = self.get_retailer_config(retailer)
        
        # Apply emergency throttling if needed
        if self.emergency_throttling:
            # This would be set by the health monitor
            multiplier = getattr(self, '_emergency_multiplier', 1.0)
            return int(config.scraping_interval_minutes * multiplier)
        
        return config.scraping_interval_minutes
    
    def should_use_fallback(self, retailer: str, failure_count: int) -> bool:
        """Determine if fallback methods should be used"""
        config = self.get_retailer_config(retailer)
        strategy_settings = self.get_strategy_settings(config.strategy)
        
        if failure_count >= config.consecutive_failures_critical:
            return True
        
        if failure_count >= config.consecutive_failures_warning:
            return strategy_settings.get("try_all_methods", False)
        
        return False
    
    def update_retailer_config(self, retailer: str, **kwargs):
        """Update retailer configuration"""
        if retailer not in self.retailers:
            self.retailers[retailer] = RetailerConfig()
        
        config = self.retailers[retailer]
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
    
    def enable_emergency_mode(self):
        """Enable emergency mode - more conservative scraping"""
        self._emergency_multiplier = 3.0
        for retailer, config in self.retailers.items():
            config.strategy = ScrapingStrategy.CONSERVATIVE
            config.max_concurrent_requests = 1
    
    def disable_emergency_mode(self):
        """Disable emergency mode"""
        self._emergency_multiplier = 1.0
        # Reset to default strategies (you might want to store originals)
    
    def get_health_config(self) -> Dict[str, Any]:
        """Get health monitoring configuration"""
        return {
            "enabled": self.health_monitoring_enabled,
            "check_interval": self.health_check_interval,
            "auto_healing": self.auto_healing_enabled,
            "circuit_breaker": self.circuit_breaker_enabled,
            "alert_cooldown": self.alert_cooldown_minutes,
            "emergency_thresholds": self.emergency_thresholds
        }
    
    def export_config(self) -> Dict[str, Any]:
        """Export configuration as dictionary"""
        return {
            "global_settings": {
                "enabled": self.global_enabled,
                "health_monitoring": self.health_monitoring_enabled,
                "auto_healing": self.auto_healing_enabled,
                "circuit_breaker": self.circuit_breaker_enabled
            },
            "performance": {
                "timeout": self.default_timeout,
                "max_retries": self.max_retries,
                "backoff_multiplier": self.backoff_multiplier
            },
            "retailers": {
                name: {
                    "enabled": config.enabled,
                    "interval": config.scraping_interval_minutes,
                    "strategy": config.strategy.value,
                    "priority": config.priority
                }
                for name, config in self.retailers.items()
            },
            "emergency": self.emergency_thresholds,
            "notifications": self.notifications,
            "data_quality": self.data_quality
        }
    
    def load_config(self, config_dict: Dict[str, Any]):
        """Load configuration from dictionary"""
        # This would load configuration from saved settings
        # Implementation would depend on how you want to store/load configs
        pass


# Global configuration instance
scraper_config = ScraperConfiguration()


# Example usage and helper functions
def get_safe_scraping_config():
    """Get a very safe scraping configuration"""
    safe_config = ScraperConfiguration()
    
    # Very conservative settings
    for retailer, config in safe_config.retailers.items():
        config.strategy = ScrapingStrategy.CONSERVATIVE
        config.scraping_interval_minutes *= 3  # 3x slower
        config.max_concurrent_requests = 1
        config.request_delay_range = (5.0, 10.0)  # Much longer delays
    
    return safe_config


def get_aggressive_scraping_config():
    """Get an aggressive scraping configuration for testing"""
    aggressive_config = ScraperConfiguration()
    
    # Aggressive settings
    for retailer, config in aggressive_config.retailers.items():
        config.strategy = ScrapingStrategy.AGGRESSIVE
        config.scraping_interval_minutes = max(2, config.scraping_interval_minutes // 2)
        config.max_concurrent_requests = 5
        config.request_delay_range = (0.5, 1.5)
    
    return aggressive_config


def apply_retailer_specific_fixes():
    """Apply known fixes for specific retailers"""
    # Nike fixes
    scraper_config.update_retailer_config("nike", 
        request_delay_range=(3.0, 6.0),  # Nike is very strict
        custom_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0"
        }
    )
    
    # StockX optimizations
    scraper_config.update_retailer_config("stockx",
        strategy=ScrapingStrategy.AGGRESSIVE,  # StockX APIs are more reliable
        max_concurrent_requests=4
    )
    
    # FootLocker requires stealth
    scraper_config.update_retailer_config("footlocker",
        strategy=ScrapingStrategy.STEALTH,
        request_delay_range=(4.0, 8.0)
    )


# Apply known fixes on import
apply_retailer_specific_fixes()
