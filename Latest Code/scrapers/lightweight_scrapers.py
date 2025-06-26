"""
Lightweight scrapers for Render.com deployment
No heavy dependencies, focused on core functionality
"""
import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from loguru import logger


class BaseLightweightScraper:
    """Base class for lightweight scrapers"""
    
    def __init__(self, retailer_name: str):
        self.retailer_name = retailer_name
        self.ua = UserAgent()
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": self.ua.random}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, url: str, **kwargs) -> Optional[aiohttp.ClientResponse]:
        """Make HTTP request with basic retry"""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # Random delay to avoid rate limiting
                if attempt > 0:
                    await asyncio.sleep(1 + attempt)
                
                # Rotate User-Agent
                headers = kwargs.get("headers", {})
                headers.update({"User-Agent": self.ua.random})
                kwargs["headers"] = headers
                
                async with self.session.get(url, **kwargs) as response:
                    if response.status == 200:
                        return response
                    elif response.status == 429:
                        logger.warning(f"Rate limited on {url}")
                        await asyncio.sleep(5)
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1})")
            except Exception as e:
                logger.warning(f"Request failed for {url}: {e}")
        
        return None
    
    def _parse_html(self, html_content: str) -> BeautifulSoup:
        """Parse HTML content"""
        return BeautifulSoup(html_content, 'html.parser')
    
    def _extract_price(self, price_text: str) -> Optional[float]:
        """Extract price from text"""
        if not price_text:
            return None
        
        # Remove currency symbols and spaces
        price_text = re.sub(r'[^\d.,]', '', price_text.strip())
        
        try:
            # Handle different number formats
            if ',' in price_text and '.' in price_text:
                if price_text.rindex(',') > price_text.rindex('.'):
                    price_text = price_text.replace('.', '').replace(',', '.')
                else:
                    price_text = price_text.replace(',', '')
            elif ',' in price_text:
                if len(price_text.split(',')[-1]) == 2:
                    price_text = price_text.replace(',', '.')
                else:
                    price_text = price_text.replace(',', '')
            
            return float(price_text)
        except ValueError:
            # Try to extract first number
            matches = re.findall(r'\d+\.?\d*', price_text)
            if matches:
                try:
                    return float(matches[0])
                except ValueError:
                    pass
        
        return None
    
    def _create_product_dict(self, name: str, price: Optional[float], url: str, 
                           image: Optional[str] = None, sizes: List[str] = None,
                           in_stock: bool = True) -> Dict[str, Any]:
        """Create standardized product dictionary"""
        return {
            'name': name.strip() if name else '',
            'retailer': self.retailer_name,
            'price': price,
            'url': url,
            'image': image,
            'sizes': sizes or [],
            'in_stock': in_stock,
            'scraped_at': datetime.utcnow().isoformat()
        }
    
    async def search_products(self, keyword: str) -> List[Dict[str, Any]]:
        """Search for products - to be implemented by subclasses"""
        raise NotImplementedError


class LightweightNikeScraper(BaseLightweightScraper):
    """Lightweight Nike scraper"""
    
    def __init__(self):
        super().__init__("Nike")
        self.base_url = "https://www.nike.com"
    
    async def search_products(self, keyword: str) -> List[Dict[str, Any]]:
        """Search Nike products"""
        products = []
        
        try:
            async with self:
                # Try Nike search page
                search_url = f"{self.base_url}/w/shoes-y7ok?q={keyword.replace(' ', '%20')}"
                
                response = await self._make_request(search_url)
                if not response:
                    return products
                
                html = await response.text()
                soup = self._parse_html(html)
                
                # Look for product cards
                product_cards = soup.find_all(['div', 'article'], class_=re.compile(r'product-card|grid-item'))
                
                for card in product_cards[:5]:  # Limit to 5 products
                    try:
                        product = await self._parse_nike_product_card(card)
                        if product:
                            products.append(product)
                    except Exception as e:
                        logger.debug(f"Failed to parse Nike product card: {e}")
                        continue
                
                logger.info(f"Nike found {len(products)} products for '{keyword}'")
                
        except Exception as e:
            logger.error(f"Nike search failed: {e}")
        
        return products
    
    async def _parse_nike_product_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse Nike product card"""
        try:
            # Extract name
            name_elem = card.find(['h3', 'h2', 'h1'], class_=re.compile(r'product-card__title|headline'))
            if not name_elem:
                name_elem = card.find('a')
                name = name_elem.get('aria-label', '') if name_elem else ''
            else:
                name = name_elem.get_text(strip=True)
            
            if not name:
                return None
            
            # Extract price
            price = None
            price_elem = card.find(['div', 'span'], class_=re.compile(r'product-price|price'))
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                price = self._extract_price(price_text)
            
            # Extract URL
            url = None
            link_elem = card.find('a', href=True)
            if link_elem:
                href = link_elem['href']
                if href.startswith('/'):
                    url = f"{self.base_url}{href}"
                else:
                    url = href
            
            # Extract image
            image = None
            img_elem = card.find('img')
            if img_elem:
                image = img_elem.get('src') or img_elem.get('data-src')
            
            if name and url:
                return self._create_product_dict(name, price, url, image)
            
        except Exception as e:
            logger.debug(f"Nike card parsing error: {e}")
        
        return None


class LightweightStockXScraper(BaseLightweightScraper):
    """Lightweight StockX scraper"""
    
    def __init__(self):
        super().__init__("StockX")
        self.base_url = "https://stockx.com"
    
    async def search_products(self, keyword: str) -> List[Dict[str, Any]]:
        """Search StockX products"""
        products = []
        
        try:
            async with self:
                # Try StockX search
                search_url = f"{self.base_url}/search?s={keyword.replace(' ', '%20')}"
                
                response = await self._make_request(search_url)
                if not response:
                    return products
                
                html = await response.text()
                soup = self._parse_html(html)
                
                # Look for product items
                product_items = soup.find_all(['div', 'article'], class_=re.compile(r'browse-grid-item|product-item'))
                
                for item in product_items[:5]:  # Limit to 5 products
                    try:
                        product = await self._parse_stockx_product_item(item)
                        if product:
                            products.append(product)
                    except Exception as e:
                        logger.debug(f"Failed to parse StockX product: {e}")
                        continue
                
                logger.info(f"StockX found {len(products)} products for '{keyword}'")
                
        except Exception as e:
            logger.error(f"StockX search failed: {e}")
        
        return products
    
    async def _parse_stockx_product_item(self, item) -> Optional[Dict[str, Any]]:
        """Parse StockX product item"""
        try:
            # Extract name
            name_elem = item.find(['h3', 'h2', 'div'], class_=re.compile(r'name|title'))
            if not name_elem:
                # Look for any text that might be the product name
                name_elem = item.find('a')
            
            name = name_elem.get_text(strip=True) if name_elem else ''
            if not name:
                return None
            
            # Extract price (lowest ask)
            price = None
            price_elems = item.find_all(['div', 'span'], string=re.compile(r'\$\d+'))
            for price_elem in price_elems:
                price_text = price_elem.get_text(strip=True)
                price = self._extract_price(price_text)
                if price:
                    break
            
            # Extract URL
            url = None
            link_elem = item.find('a', href=True)
            if link_elem:
                href = link_elem['href']
                if href.startswith('/'):
                    url = f"{self.base_url}{href}"
                else:
                    url = href
            
            # Extract image
            image = None
            img_elem = item.find('img')
            if img_elem:
                image = img_elem.get('src') or img_elem.get('data-src')
            
            if name and url:
                return self._create_product_dict(name, price, url, image)
            
        except Exception as e:
            logger.debug(f"StockX item parsing error: {e}")
        
        return None


class LightweightAdidasScraper(BaseLightweightScraper):
    """Lightweight Adidas scraper"""
    
    def __init__(self):
        super().__init__("Adidas")
        self.base_url = "https://www.adidas.com"
    
    async def search_products(self, keyword: str) -> List[Dict[str, Any]]:
        """Search Adidas products"""
        products = []
        
        try:
            async with self:
                # Try Adidas search
                search_url = f"{self.base_url}/us/search?q={keyword.replace(' ', '%20')}"
                
                response = await self._make_request(search_url)
                if not response:
                    return products
                
                html = await response.text()
                soup = self._parse_html(html)
                
                # Look for product cards
                product_cards = soup.find_all(['div'], class_=re.compile(r'product-item|grid-item|plp-product'))
                
                for card in product_cards[:5]:  # Limit to 5 products
                    try:
                        product = await self._parse_adidas_product_card(card)
                        if product:
                            products.append(product)
                    except Exception as e:
                        logger.debug(f"Failed to parse Adidas product: {e}")
                        continue
                
                logger.info(f"Adidas found {len(products)} products for '{keyword}'")
                
        except Exception as e:
            logger.error(f"Adidas search failed: {e}")
        
        return products
    
    async def _parse_adidas_product_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse Adidas product card"""
        try:
            # Extract name
            name_elem = card.find(['h3', 'h2', 'span'], class_=re.compile(r'product-title|name'))
            name = name_elem.get_text(strip=True) if name_elem else ''
            
            if not name:
                return None
            
            # Extract price
            price = None
            price_elem = card.find(['div', 'span'], class_=re.compile(r'price|cost'))
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                price = self._extract_price(price_text)
            
            # Extract URL
            url = None
            link_elem = card.find('a', href=True)
            if link_elem:
                href = link_elem['href']
                if href.startswith('/'):
                    url = f"{self.base_url}{href}"
                else:
                    url = href
            
            # Extract image
            image = None
            img_elem = card.find('img')
            if img_elem:
                image = img_elem.get('src') or img_elem.get('data-src')
            
            if name and url:
                return self._create_product_dict(name, price, url, image)
            
        except Exception as e:
            logger.debug(f"Adidas card parsing error: {e}")
        
        return None


class MockScraper(BaseLightweightScraper):
    """Mock scraper for development and fallback"""
    
    def __init__(self, retailer_name: str):
        super().__init__(retailer_name)
        
        # Sample mock data
        self.mock_products = [
            {
                'name': f'Jordan 4 Bred - {retailer_name}',
                'price': 210.0,
                'url': f'https://{retailer_name.lower()}.com/jordan-4-bred',
                'image': f'https://via.placeholder.com/300x300?text={retailer_name}',
                'sizes': ['8', '8.5', '9', '9.5', '10', '10.5', '11'],
                'in_stock': True
            },
            {
                'name': f'Yeezy 350 Cream - {retailer_name}',
                'price': 220.0,
                'url': f'https://{retailer_name.lower()}.com/yeezy-350-cream',
                'image': f'https://via.placeholder.com/300x300?text={retailer_name}',
                'sizes': ['7', '7.5', '8', '8.5', '9', '9.5', '10'],
                'in_stock': False
            }
        ]
    
    async def search_products(self, keyword: str) -> List[Dict[str, Any]]:
        """Return mock products"""
        # Simulate search delay
        await asyncio.sleep(0.5)
        
        # Filter mock products based on keyword
        keyword_lower = keyword.lower()
        matching_products = []
        
        for product in self.mock_products:
            if any(word in product['name'].lower() for word in keyword_lower.split()):
                product_copy = product.copy()
                product_copy['retailer'] = self.retailer_name
                product_copy['scraped_at'] = datetime.utcnow().isoformat()
                matching_products.append(product_copy)
        
        logger.info(f"Mock {self.retailer_name} found {len(matching_products)} products for '{keyword}'")
        return matching_products
