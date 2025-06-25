"""
Enhanced base scraper with robust failover and schema validation
"""
import asyncio
import random
import json
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import aiohttp
import re
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from loguru import logger
from urllib.parse import urljoin, urlparse

from config.settings import settings
from database.models import SneakerProduct, SneakerSize, Retailer


class ScrapingMethod(Enum):
    """Available scraping methods in order of preference"""
    OFFICIAL_API = "official_api"
    JSON_LD = "json_ld"
    SCRIPT_JSON = "script_json"
    HTML_STRUCTURED = "html_structured"
    HTML_FALLBACK = "html_fallback"


@dataclass
class ScrapingResult:
    """Result of a scraping attempt"""
    success: bool
    method: ScrapingMethod
    data: Optional[Dict] = None
    error: Optional[str] = None
    confidence: float = 0.0  # 0-1 confidence in data quality


@dataclass
class ProductValidation:
    """Product data validation result"""
    is_valid: bool
    missing_fields: List[str]
    invalid_fields: List[str]
    confidence_score: float


class EnhancedBaseScraper(ABC):
    """Enhanced base scraper with multiple fallback strategies"""
    
    def __init__(self, retailer: Retailer):
        self.retailer = retailer
        self.ua = UserAgent()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Circuit breaker settings
        self.failure_count = 0
        self.last_failure_time = None
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 300  # 5 minutes
        
        # Health monitoring
        self.health_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "method_success": {method: 0 for method in ScrapingMethod},
            "last_successful_scrape": None,
            "consecutive_failures": 0
        }
        
        # Required product fields for validation
        self.required_fields = ["name", "price", "url"]
        self.important_fields = ["brand", "model", "sku", "image"]
        
    async def __aenter__(self):
        """Async context manager entry with proxy rotation"""
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        # Rotate user agents more aggressively
        headers = {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        # Add proxy if configured
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=3,
            enable_cleanup_closed=True
        )
        
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers,
            connector=connector
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open"""
        if self.failure_count < self.circuit_breaker_threshold:
            return False
        
        if self.last_failure_time:
            time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
            return time_since_failure < self.circuit_breaker_timeout
        
        return True
    
    def record_success(self):
        """Record successful operation"""
        self.failure_count = 0
        self.last_failure_time = None
        self.health_stats["successful_requests"] += 1
        self.health_stats["consecutive_failures"] = 0
        self.health_stats["last_successful_scrape"] = datetime.now()
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        self.health_stats["consecutive_failures"] += 1
    
    async def _make_robust_request(self, url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
        """Make HTTP request with enhanced retry logic and monitoring"""
        if self.is_circuit_breaker_open():
            logger.warning(f"Circuit breaker open for {self.retailer.value}, skipping request")
            return None
        
        self.health_stats["total_requests"] += 1
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                # Exponential backoff with jitter
                if attempt > 0:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                
                # Rotate User-Agent for each attempt
                headers = kwargs.get("headers", {})
                headers.update({
                    "User-Agent": self.ua.random,
                    "X-Forwarded-For": f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
                })
                kwargs["headers"] = headers
                
                async with self.session.get(url, **kwargs) as response:
                    if response.status == 200:
                        self.record_success()
                        return response
                    elif response.status == 429:  # Rate limited
                        wait_time = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"Rate limited on {url}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    elif response.status == 403:  # Forbidden - might be blocked
                        logger.warning(f"Forbidden access to {url} - might be blocked")
                        await asyncio.sleep(5)  # Wait longer for forbidden
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1})")
            except aiohttp.ClientConnectorError as e:
                logger.warning(f"Connection error for {url}: {e}")
            except Exception as e:
                logger.error(f"Request failed for {url}: {e}")
        
        self.record_failure()
        logger.error(f"Failed to fetch {url} after {max_retries} attempts")
        return None
    
    async def _try_multiple_parsing_methods(self, html_content: str, url: str) -> ScrapingResult:
        """Try multiple parsing methods in order of reliability"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Method 1: Look for JSON-LD structured data (most reliable)
        result = await self._try_json_ld_parsing(soup)
        if result.success:
            return result
        
        # Method 2: Look for product JSON in script tags
        result = await self._try_script_json_parsing(soup)
        if result.success:
            return result
        
        # Method 3: Try structured HTML parsing with multiple selectors
        result = await self._try_structured_html_parsing(soup, url)
        if result.success:
            return result
        
        # Method 4: Fallback to aggressive HTML parsing
        result = await self._try_fallback_html_parsing(soup, url)
        return result
    
    async def _try_json_ld_parsing(self, soup: BeautifulSoup) -> ScrapingResult:
        """Try to extract product data from JSON-LD"""
        try:
            json_ld_scripts = soup.find_all("script", type="application/ld+json")
            
            for script in json_ld_scripts:
                if not script.string:
                    continue
                
                try:
                    data = json.loads(script.string)
                    
                    # Handle both single objects and arrays
                    items = data if isinstance(data, list) else [data]
                    
                    for item in items:
                        if item.get("@type") in ["Product", "ProductModel"]:
                            validated = self._validate_product_data(item)
                            if validated.is_valid:
                                return ScrapingResult(
                                    success=True,
                                    method=ScrapingMethod.JSON_LD,
                                    data=item,
                                    confidence=validated.confidence_score
                                )
                except json.JSONDecodeError:
                    continue
            
            return ScrapingResult(success=False, method=ScrapingMethod.JSON_LD, error="No valid JSON-LD found")
            
        except Exception as e:
            return ScrapingResult(success=False, method=ScrapingMethod.JSON_LD, error=str(e))
    
    async def _try_script_json_parsing(self, soup: BeautifulSoup) -> ScrapingResult:
        """Try to extract product data from script tags containing JSON"""
        try:
            scripts = soup.find_all("script")
            
            # Common patterns to look for
            patterns = [
                (r'window\.__INITIAL_STATE__\s*=\s*({.+?});', 'window.__INITIAL_STATE__'),
                (r'window\.__PRELOADED_STATE__\s*=\s*({.+?});', 'window.__PRELOADED_STATE__'),
                (r'window\.INITIAL_REDUX_STATE\s*=\s*({.+?});', 'window.INITIAL_REDUX_STATE'),
                (r'window\.APP_STATE\s*=\s*({.+?});', 'window.APP_STATE'),
                (r'"product"\s*:\s*({.+?})', 'product object'),
                (r'"productDetails"\s*:\s*({.+?})', 'productDetails object'),
            ]
            
            for script in scripts:
                if not script.string:
                    continue
                
                for pattern, name in patterns:
                    matches = re.search(pattern, script.string, re.DOTALL)
                    if matches:
                        try:
                            json_str = matches.group(1)
                            data = json.loads(json_str)
                            
                            # Navigate through common data structures
                            product_data = self._extract_product_from_json(data)
                            if product_data:
                                validated = self._validate_product_data(product_data)
                                if validated.confidence_score > 0.5:
                                    return ScrapingResult(
                                        success=True,
                                        method=ScrapingMethod.SCRIPT_JSON,
                                        data=product_data,
                                        confidence=validated.confidence_score
                                    )
                        except json.JSONDecodeError:
                            continue
            
            return ScrapingResult(success=False, method=ScrapingMethod.SCRIPT_JSON, error="No valid script JSON found")
            
        except Exception as e:
            return ScrapingResult(success=False, method=ScrapingMethod.SCRIPT_JSON, error=str(e))
    
    def _extract_product_from_json(self, data: Dict) -> Optional[Dict]:
        """Extract product data from nested JSON structures"""
        # Common paths to product data
        paths = [
            ["product"],
            ["productDetails"],
            ["data", "product"],
            ["props", "pageProps", "product"],
            ["initialState", "product"],
            ["product", "current"],
        ]
        
        for path in paths:
            current = data
            try:
                for key in path:
                    if isinstance(current, dict) and key in current:
                        current = current[key]
                    else:
                        break
                else:
                    # Successful navigation through path
                    if isinstance(current, dict) and any(field in current for field in self.required_fields):
                        return current
            except (KeyError, TypeError):
                continue
        
        return None
    
    async def _try_structured_html_parsing(self, soup: BeautifulSoup, url: str) -> ScrapingResult:
        """Try structured HTML parsing with multiple selector strategies"""
        try:
            # Define multiple selector strategies for common elements
            selectors = {
                "title": [
                    "h1[data-testid*='product-title']",
                    "h1.product-title",
                    "h1.pdp-product-title",
                    "h1[class*='title']",
                    "h1[class*='product']",
                    ".product-name h1",
                    ".product-title",
                    "[data-testid='product-name']",
                    "h1"
                ],
                "price": [
                    "[data-testid*='price']",
                    ".price",
                    ".product-price",
                    "[class*='price']",
                    ".price-current",
                    ".current-price",
                    "[data-price]"
                ],
                "image": [
                    "[data-testid*='product-image'] img",
                    ".product-image img",
                    ".hero-image img",
                    ".main-image img",
                    "img[class*='product']",
                    "picture img"
                ],
                "sku": [
                    "[data-testid*='sku']",
                    ".sku",
                    ".style-code",
                    "[class*='sku']",
                    "[class*='style']"
                ]
            }
            
            extracted_data = {"url": url}
            confidence_factors = []
            
            for field, selector_list in selectors.items():
                found = False
                for selector in selector_list:
                    try:
                        element = soup.select_one(selector)
                        if element:
                            if field == "image":
                                value = element.get("src") or element.get("data-src")
                            else:
                                value = element.get_text(strip=True)
                            
                            if value and value.strip():
                                extracted_data[field] = value.strip()
                                confidence_factors.append(1.0)
                                found = True
                                break
                    except Exception:
                        continue
                
                if not found:
                    confidence_factors.append(0.0)
            
            confidence = sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.0
            
            validated = self._validate_product_data(extracted_data)
            if validated.confidence_score > 0.3:
                return ScrapingResult(
                    success=True,
                    method=ScrapingMethod.HTML_STRUCTURED,
                    data=extracted_data,
                    confidence=min(confidence, validated.confidence_score)
                )
            
            return ScrapingResult(
                success=False,
                method=ScrapingMethod.HTML_STRUCTURED,
                error=f"Low confidence: {validated.confidence_score}"
            )
            
        except Exception as e:
            return ScrapingResult(success=False, method=ScrapingMethod.HTML_STRUCTURED, error=str(e))
    
    async def _try_fallback_html_parsing(self, soup: BeautifulSoup, url: str) -> ScrapingResult:
        """Aggressive fallback HTML parsing when all else fails"""
        try:
            extracted_data = {"url": url}
            
            # Look for any text that looks like a price
            price_patterns = [
                r'\$[\d,]+\.?\d*',
                r'USD\s*[\d,]+\.?\d*',
                r'[\d,]+\.?\d*\s*USD',
                r'Price:\s*\$?([\d,]+\.?\d*)'
            ]
            
            page_text = soup.get_text()
            for pattern in price_patterns:
                matches = re.findall(pattern, page_text)
                if matches:
                    # Take the first reasonable price (between $10 and $2000)
                    for match in matches:
                        price_num = re.findall(r'[\d,]+\.?\d*', match)
                        if price_num:
                            try:
                                price = float(price_num[0].replace(',', ''))
                                if 10 <= price <= 2000:
                                    extracted_data["price"] = price
                                    break
                            except ValueError:
                                continue
                    if "price" in extracted_data:
                        break
            
            # Try to find any h1 as title
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)
                if title and len(title) > 5:  # Reasonable title length
                    extracted_data["title"] = title
            
            # Look for images
            images = soup.find_all("img")
            for img in images:
                src = img.get("src") or img.get("data-src")
                if src and any(keyword in src.lower() for keyword in ["product", "shoe", "sneaker"]):
                    extracted_data["image"] = src
                    break
            
            validated = self._validate_product_data(extracted_data)
            
            return ScrapingResult(
                success=validated.confidence_score > 0.1,  # Very low threshold for fallback
                method=ScrapingMethod.HTML_FALLBACK,
                data=extracted_data,
                confidence=validated.confidence_score
            )
            
        except Exception as e:
            return ScrapingResult(success=False, method=ScrapingMethod.HTML_FALLBACK, error=str(e))
    
    def _validate_product_data(self, data: Dict) -> ProductValidation:
        """Validate extracted product data"""
        missing_fields = []
        invalid_fields = []
        
        # Check required fields
        for field in self.required_fields:
            if field not in data or not data[field]:
                missing_fields.append(field)
        
        # Validate field content
        if "price" in data:
            try:
                price = self._extract_price(str(data["price"]))
                if not price or price <= 0 or price > 10000:
                    invalid_fields.append("price")
            except:
                invalid_fields.append("price")
        
        if "name" in data or "title" in data:
            name = data.get("name") or data.get("title", "")
            if len(name.strip()) < 3:
                invalid_fields.append("name")
        
        if "url" in data:
            url = data["url"]
            if not url.startswith(("http://", "https://")):
                invalid_fields.append("url")
        
        # Calculate confidence score
        total_possible_fields = len(self.required_fields) + len(self.important_fields)
        valid_required = len(self.required_fields) - len(missing_fields)
        valid_important = sum(1 for field in self.important_fields if field in data and data[field])
        invalid_penalty = len(invalid_fields) * 0.2
        
        confidence_score = max(0, (valid_required * 0.7 + valid_important * 0.3) / total_possible_fields - invalid_penalty)
        
        is_valid = len(missing_fields) == 0 and len(invalid_fields) == 0
        
        return ProductValidation(
            is_valid=is_valid,
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
            confidence_score=confidence_score
        )
    
    def _extract_price(self, price_text: str) -> Optional[float]:
        """Enhanced price extraction with multiple formats"""
        if not price_text:
            return None
        
        # Remove common currency symbols and whitespace
        price_text = re.sub(r'[^\d.,]', '', price_text.strip())
        
        # Handle different number formats
        if ',' in price_text and '.' in price_text:
            # Determine if comma is thousands separator or decimal
            if price_text.rindex(',') > price_text.rindex('.'):
                # Comma is decimal separator (European format)
                price_text = price_text.replace('.', '').replace(',', '.')
            else:
                # Comma is thousands separator
                price_text = price_text.replace(',', '')
        elif ',' in price_text:
            # Could be thousands separator or decimal
            if len(price_text.split(',')[-1]) == 2:
                # Likely decimal
                price_text = price_text.replace(',', '.')
            else:
                # Likely thousands separator
                price_text = price_text.replace(',', '')
        
        try:
            return float(price_text)
        except ValueError:
            # Last resort: extract first number sequence
            matches = re.findall(r'\d+\.?\d*', price_text)
            if matches:
                try:
                    return float(matches[0])
                except ValueError:
                    pass
        
        return None
    
    async def health_check(self) -> Dict[str, Any]:
        """Enhanced health check with detailed stats"""
        try:
            # Test basic connectivity
            response = await self._make_robust_request("https://httpbin.org/get")
            connectivity = response is not None
            
            # Calculate success rate
            total = self.health_stats["total_requests"]
            successful = self.health_stats["successful_requests"]
            success_rate = successful / total if total > 0 else 0
            
            # Check if recently successful
            last_success = self.health_stats["last_successful_scrape"]
            recently_successful = (
                last_success and 
                (datetime.now() - last_success) < timedelta(hours=1)
            ) if last_success else False
            
            health_status = {
                "retailer": self.retailer.value,
                "connectivity": connectivity,
                "success_rate": success_rate,
                "total_requests": total,
                "successful_requests": successful,
                "consecutive_failures": self.health_stats["consecutive_failures"],
                "circuit_breaker_open": self.is_circuit_breaker_open(),
                "recently_successful": recently_successful,
                "method_success_rates": {
                    method.value: self.health_stats["method_success"][method] / total if total > 0 else 0
                    for method in ScrapingMethod
                }
            }
            
            return health_status
            
        except Exception as e:
            logger.error(f"Health check failed for {self.retailer}: {e}")
            return {"retailer": self.retailer.value, "error": str(e), "healthy": False}
    
    @abstractmethod
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search for products by keyword"""
        pass
    
    @abstractmethod
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed product information"""
        pass


# Add a factory function to create enhanced scrapers
def create_enhanced_scraper(retailer: Retailer) -> EnhancedBaseScraper:
    """Factory function to create enhanced scrapers"""
    # Import specific scrapers here to avoid circular imports
    from scrapers.enhanced_nike_scraper import EnhancedNikeScraper
    from scrapers.enhanced_stockx_scraper import EnhancedStockXScraper
    # Add other enhanced scrapers as needed
    
    scraper_map = {
        Retailer.NIKE: EnhancedNikeScraper,
        Retailer.STOCKX: EnhancedStockXScraper,
        # Add mappings for other retailers
    }
    
    scraper_class = scraper_map.get(retailer)
    if scraper_class:
        return scraper_class()
    else:
        # Fallback to mock scraper for unsupported retailers
        from scrapers.base_scraper import MockScraper
        return MockScraper(retailer)
