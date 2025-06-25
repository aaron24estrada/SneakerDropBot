"""
Utility functions and helpers
"""
import re
import hashlib
from typing import Optional, Dict, Any
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
from datetime import datetime
from loguru import logger

from config.settings import settings
from database.models import Retailer


def generate_affiliate_link(original_url: str, retailer: Retailer) -> str:
    """Generate affiliate link for a product URL"""
    try:
        # Affiliate ID mappings
        affiliate_ids = {
            Retailer.STOCKX: settings.stockx_affiliate_id,
            Retailer.GOAT: settings.goat_affiliate_id,
            Retailer.STADIUM_GOODS: settings.stadium_goods_affiliate_id,
        }
        
        affiliate_id = affiliate_ids.get(retailer)
        if not affiliate_id:
            return original_url
        
        # Parse URL
        parsed_url = urlparse(original_url)
        query_params = parse_qs(parsed_url.query)
        
        # Add affiliate parameters based on retailer
        if retailer == Retailer.STOCKX:
            query_params['affiliate'] = [affiliate_id]
            query_params['utm_source'] = ['sneakerdropbot']
            query_params['utm_medium'] = ['telegram']
            query_params['utm_campaign'] = ['bot_alert']
        
        elif retailer == Retailer.GOAT:
            query_params['ref'] = [affiliate_id]
            query_params['utm_source'] = ['sneakerdropbot']
        
        elif retailer == Retailer.STADIUM_GOODS:
            query_params['partner'] = [affiliate_id]
        
        # Rebuild URL with affiliate parameters
        new_query = urlencode(query_params, doseq=True)
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))
        
        return new_url
    
    except Exception as e:
        logger.error(f"Failed to generate affiliate link for {original_url}: {e}")
        return original_url


def format_price(price: Optional[float]) -> str:
    """Format price for display"""
    if price is None:
        return "Price unavailable"
    
    return f"${price:.2f}"


def format_currency(amount: float, currency: str = "USD") -> str:
    """Format currency amount"""
    if currency.upper() == "USD":
        return f"${amount:.2f}"
    else:
        return f"{amount:.2f} {currency}"


def format_percentage(value: float) -> str:
    """Format percentage for display"""
    return f"{value:.1f}%"


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to specified length"""
    if len(text) <= max_length:
        return text
    
    return text[:max_length - 3] + "..."


def clean_sneaker_name(name: str) -> str:
    """Clean and normalize sneaker name"""
    if not name:
        return ""
    
    # Remove extra whitespace
    name = re.sub(r'\s+', ' ', name.strip())
    
    # Remove common suffixes
    suffixes_to_remove = [
        r'\s*-\s*Men\'s.*$',
        r'\s*-\s*Women\'s.*$',
        r'\s*-\s*Kids.*$',
        r'\s*-\s*Unisex.*$',
        r'\s*Sneaker.*$',
        r'\s*Shoe.*$'
    ]
    
    for suffix in suffixes_to_remove:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    
    # Normalize common terms
    replacements = {
        r'\bAir\s+Jordan\b': 'Jordan',
        r'\bNike\s+Air\s+Max\b': 'Air Max',
        r'\bAdidas\s+Yeezy\b': 'Yeezy',
        r'\bNike\s+Dunk\b': 'Dunk'
    }
    
    for pattern, replacement in replacements.items():
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    
    return name.strip().title()


def extract_size_from_text(text: str) -> Optional[float]:
    """Extract shoe size from text"""
    if not text:
        return None
    
    # Look for patterns like "Size 10", "10.5", "US 9"
    patterns = [
        r'size\s*(\d+(?:\.\d+)?)',
        r'us\s*(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*us',
        r'\b(\d+(?:\.\d+)?)\b'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            try:
                size = float(match.group(1))
                if 4.0 <= size <= 18.0:  # Valid shoe size range
                    return size
            except ValueError:
                continue
    
    return None


def generate_tracking_id() -> str:
    """Generate unique tracking ID"""
    timestamp = str(int(datetime.utcnow().timestamp()))
    hash_obj = hashlib.md5(timestamp.encode())
    return hash_obj.hexdigest()[:8].upper()


def validate_email(email: str) -> bool:
    """Validate email address"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    
    # Limit length
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    
    return sanitized


def calculate_profit_margin(buy_price: float, sell_price: float) -> Dict[str, float]:
    """Calculate profit margin and related metrics"""
    if buy_price <= 0:
        return {"margin": 0, "margin_percentage": 0, "roi": 0}
    
    margin = sell_price - buy_price
    margin_percentage = (margin / buy_price) * 100
    roi = (margin / buy_price) * 100
    
    return {
        "margin": margin,
        "margin_percentage": margin_percentage,
        "roi": roi
    }


def format_time_ago(dt: datetime) -> str:
    """Format datetime as 'time ago' string"""
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days > 0:
        if diff.days == 1:
            return "1 day ago"
        return f"{diff.days} days ago"
    
    hours = diff.seconds // 3600
    if hours > 0:
        if hours == 1:
            return "1 hour ago"
        return f"{hours} hours ago"
    
    minutes = diff.seconds // 60
    if minutes > 0:
        if minutes == 1:
            return "1 minute ago"
        return f"{minutes} minutes ago"
    
    return "Just now"


def is_valid_sneaker_size(size: float) -> bool:
    """Check if size is a valid sneaker size"""
    return 4.0 <= size <= 18.0


def normalize_brand_name(brand: str) -> str:
    """Normalize brand name"""
    if not brand:
        return ""
    
    brand_mappings = {
        "nike": "Nike",
        "jordan": "Jordan",
        "adidas": "Adidas",
        "yeezy": "Yeezy",
        "new balance": "New Balance",
        "puma": "Puma",
        "reebok": "Reebok",
        "vans": "Vans",
        "converse": "Converse"
    }
    
    brand_lower = brand.lower().strip()
    return brand_mappings.get(brand_lower, brand.title())


def extract_sku_from_text(text: str) -> Optional[str]:
    """Extract SKU/style code from text"""
    if not text:
        return None
    
    # Common SKU patterns
    patterns = [
        r'[A-Z]{2}\d{4}-\d{3}',  # Nike pattern: CW2288-111
        r'[A-Z]\d{5}',           # Simple pattern: H68013
        r'\d{6}-\d{3}',          # Number pattern: 308497-060
        r'[A-Z]{1,3}\d{3,5}',    # Generic pattern: DZ5485
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text.upper())
        if match:
            return match.group(0)
    
    return None


def format_alert_message(alert_type: str, product_name: str, **kwargs) -> str:
    """Format alert message based on type"""
    emoji_map = {
        "restock": "🔁",
        "price_drop": "💸",
        "flip_opportunity": "📈"
    }
    
    emoji = emoji_map.get(alert_type, "🚨")
    
    if alert_type == "restock":
        return f"{emoji} **Restock Alert!** {product_name} is back in stock"
    elif alert_type == "price_drop":
        old_price = kwargs.get("old_price", 0)
        new_price = kwargs.get("new_price", 0)
        return f"{emoji} **Price Drop!** {product_name} - Now ${new_price:.2f} (was ${old_price:.2f})"
    elif alert_type == "flip_opportunity":
        margin = kwargs.get("margin_percentage", 0)
        return f"{emoji} **Flip Opportunity!** {product_name} - {margin:.1f}% profit margin"
    
    return f"{emoji} **Alert!** {product_name}"


def rate_limit_key(user_id: int, action: str) -> str:
    """Generate rate limit key for user actions"""
    return f"rate_limit:{user_id}:{action}"


def chunk_list(lst: list, chunk_size: int) -> list:
    """Split list into chunks of specified size"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to integer"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def mask_sensitive_data(data: str, mask_char: str = "*", visible_chars: int = 4) -> str:
    """Mask sensitive data for logging"""
    if len(data) <= visible_chars:
        return mask_char * len(data)
    
    return data[:visible_chars] + mask_char * (len(data) - visible_chars)


def build_search_query(keyword: str, filters: Dict[str, Any] = None) -> str:
    """Build search query with filters"""
    query = keyword.strip()
    
    if filters:
        filter_parts = []
        
        if "brand" in filters:
            filter_parts.append(f"brand:{filters['brand']}")
        
        if "max_price" in filters:
            filter_parts.append(f"price:<{filters['max_price']}")
        
        if "min_price" in filters:
            filter_parts.append(f"price:>{filters['min_price']}")
        
        if filter_parts:
            query += " " + " ".join(filter_parts)
    
    return query
