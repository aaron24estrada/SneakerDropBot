"""
Base scraper class for all retailers
"""
import asyncio
import random
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from loguru import logger

from config.settings import settings
from database.models import SneakerProduct, SneakerSize, Retailer


class BaseScraper(ABC):
    """Base class for all sneaker scrapers"""
    
    def __init__(self, retailer: Retailer):
        self.retailer = retailer
        self.ua = UserAgent()
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": self.ua.random}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    @abstractmethod
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search for products by keyword"""
        pass
    
    @abstractmethod
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed product information"""
        pass
    
    async def _make_request(self, url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
        """Make HTTP request with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Random delay to avoid rate limiting
                if attempt > 0:
                    delay = random.uniform(
                        settings.scraping_delay_min,
                        settings.scraping_delay_max
                    )
                    await asyncio.sleep(delay)
                
                # Rotate User-Agent
                headers = kwargs.get("headers", {})
                headers.update({"User-Agent": self.ua.random})
                kwargs["headers"] = headers
                
                async with self.session.get(url, **kwargs) as response:
                    if response.status == 200:
                        return response
                    elif response.status == 429:  # Rate limited
                        wait_time = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"Request failed for {url}: {e}")
        
        logger.error(f"Failed to fetch {url} after {max_retries} attempts")
        return None
    
    async def _parse_html(self, html_content: str) -> BeautifulSoup:
        """Parse HTML content"""
        return BeautifulSoup(html_content, 'html.parser')
    
    def _extract_price(self, price_text: str) -> Optional[float]:
        """Extract price from text"""
        if not price_text:
            return None
        
        # Remove currency symbols and spaces
        price_text = price_text.replace("$", "").replace(",", "").strip()
        
        try:
            return float(price_text)
        except ValueError:
            # Try to extract first number
            import re
            matches = re.findall(r'\d+\.?\d*', price_text)
            if matches:
                return float(matches[0])
        
        return None
    
    def _extract_sizes(self, sizes_data: List[Dict]) -> List[SneakerSize]:
        """Extract sizes from scraped data"""
        sizes = []
        
        for size_data in sizes_data:
            if isinstance(size_data, dict):
                us_size = size_data.get("us")
                uk_size = size_data.get("uk") 
                eu_size = size_data.get("eu")
                
                if us_size:
                    try:
                        sizes.append(SneakerSize(
                            us_size=float(us_size),
                            uk_size=float(uk_size) if uk_size else None,
                            eu_size=float(eu_size) if eu_size else None
                        ))
                    except ValueError:
                        continue
            elif isinstance(size_data, (str, int, float)):
                try:
                    sizes.append(SneakerSize(us_size=float(size_data)))
                except ValueError:
                    continue
        
        return sizes
    
    def _normalize_product_name(self, name: str) -> str:
        """Normalize product name for consistency"""
        if not name:
            return ""
        
        # Remove extra whitespace
        name = " ".join(name.split())
        
        # Common normalizations
        replacements = {
            "Air Jordan": "Jordan",
            "Nike Air Max": "Air Max",
            "Adidas Yeezy": "Yeezy",
            "Nike Dunk": "Dunk"
        }
        
        for old, new in replacements.items():
            name = name.replace(old, new)
        
        return name.title()
    
    async def health_check(self) -> bool:
        """Check if the scraper is working"""
        try:
            response = await self._make_request("https://httpbin.org/get")
            return response is not None
        except Exception as e:
            logger.error(f"Health check failed for {self.retailer}: {e}")
            return False


class MockScraper(BaseScraper):
    """Mock scraper for testing purposes"""
    
    def __init__(self, retailer: Retailer):
        super().__init__(retailer)
        self.mock_products = [
            {
                "name": "Jordan 4 Bred",
                "brand": "Jordan",
                "model": "4",
                "colorway": "Bred",
                "sku": "308497-060",
                "price": 210.0,
                "sizes": [8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12],
                "in_stock": True,
                "url": f"https://{retailer.value}.com/jordan-4-bred",
                "image": f"https://{retailer.value}.com/images/jordan-4-bred.jpg"
            },
            {
                "name": "Yeezy 350 Cream",
                "brand": "Adidas",
                "model": "350",
                "colorway": "Cream",
                "sku": "CP9366",
                "price": 220.0,
                "sizes": [7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11],
                "in_stock": False,
                "url": f"https://{retailer.value}.com/yeezy-350-cream",
                "image": f"https://{retailer.value}.com/images/yeezy-350-cream.jpg"
            },
            {
                "name": "Air Max 90 Infrared",
                "brand": "Nike",
                "model": "Air Max 90",
                "colorway": "Infrared",
                "sku": "CD0881-100",
                "price": 130.0,
                "sizes": [8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 13],
                "in_stock": True,
                "url": f"https://{retailer.value}.com/air-max-90-infrared",
                "image": f"https://{retailer.value}.com/images/air-max-90-infrared.jpg"
            }
        ]
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Mock search implementation"""
        # Simulate API delay
        await asyncio.sleep(random.uniform(1, 3))
        
        results = []
        keyword_lower = keyword.lower()
        
        for product_data in self.mock_products:
            if any(word in product_data["name"].lower() for word in keyword_lower.split()):
                product = SneakerProduct(
                    name=product_data["name"],
                    brand=product_data["brand"],
                    model=product_data["model"],
                    colorway=product_data["colorway"],
                    sku=product_data["sku"],
                    retailer=self.retailer,
                    url=product_data["url"],
                    image_url=product_data["image"],
                    price=product_data["price"],
                    sizes_available=self._extract_sizes([
                        {"us": size} for size in product_data["sizes"]
                    ]),
                    is_in_stock=product_data["in_stock"]
                )
                results.append(product)
        
        logger.info(f"Mock search for '{keyword}' found {len(results)} products")
        return results
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Mock product details implementation"""
        # Simulate API delay
        await asyncio.sleep(random.uniform(0.5, 2))
        
        # Find matching product from URL
        for product_data in self.mock_products:
            if product_data["url"] == product_url:
                # Simulate stock changes
                is_in_stock = random.choice([True, False, True])  # 66% chance in stock
                available_sizes = product_data["sizes"] if is_in_stock else []
                
                return SneakerProduct(
                    name=product_data["name"],
                    brand=product_data["brand"],
                    model=product_data["model"],
                    colorway=product_data["colorway"],
                    sku=product_data["sku"],
                    retailer=self.retailer,
                    url=product_data["url"],
                    image_url=product_data["image"],
                    price=product_data["price"],
                    sizes_available=self._extract_sizes([
                        {"us": size} for size in available_sizes
                    ]),
                    is_in_stock=is_in_stock
                )
        
        return None
