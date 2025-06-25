"""
StockX scraper with official API integration
"""
import json
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus
import aiohttp
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer, ResellData
from scrapers.base_scraper import BaseScraper
from config.settings import settings


class StockXScraper(BaseScraper):
    """StockX scraper with API integration"""
    
    def __init__(self):
        super().__init__(Retailer.STOCKX)
        self.base_url = "https://stockx.com"
        self.api_url = "https://stockx.com/api"
        self.search_url = "https://stockx.com/api/browse"
        
        # StockX API headers (these would be from official API if available)
        self.api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://stockx.com/",
            "Origin": "https://stockx.com",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search StockX for products"""
        products = []
        
        try:
            # Use StockX browse API endpoint
            search_params = {
                "category": "sneakers",
                "page": 1,
                "_search": keyword,
                "dataType": "product"
            }
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.get(self.search_url, params=search_params) as response:
                    if response.status == 200:
                        data = await response.json()
                        products = await self._parse_search_response(data, keyword)
                    else:
                        logger.warning(f"StockX search failed with status {response.status}")
                        # Fallback to web scraping
                        products = await self._fallback_web_scraping(keyword)
            
            logger.info(f"StockX search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"StockX search failed for '{keyword}': {e}")
            # Try fallback scraping
            try:
                products = await self._fallback_web_scraping(keyword)
            except Exception as fallback_error:
                logger.error(f"StockX fallback scraping also failed: {fallback_error}")
        
        return products
    
    async def _parse_search_response(self, data: Dict, keyword: str) -> List[SneakerProduct]:
        """Parse StockX API search response"""
        products = []
        
        try:
            # Parse the response structure
            if "Products" in data:
                for item in data["Products"]:
                    product = await self._create_product_from_api_item(item)
                    if product:
                        products.append(product)
            elif "products" in data:
                for item in data["products"]:
                    product = await self._create_product_from_api_item(item)
                    if product:
                        products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse StockX search response: {e}")
        
        return products
    
    async def _create_product_from_api_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from StockX API item"""
        try:
            # Extract basic info
            name = item.get("name", "")
            brand = item.get("brand", "")
            shoe_condition = item.get("shoe_condition", "")
            
            # Extract pricing
            market_data = item.get("market", {})
            lowest_ask = market_data.get("lowestAsk", 0)
            highest_bid = market_data.get("highestBid", 0)
            last_sale = market_data.get("lastSale", 0)
            
            # Use lowest ask as current price
            current_price = lowest_ask if lowest_ask > 0 else last_sale
            
            # Extract URL
            url_key = item.get("urlKey", "")
            product_url = f"https://stockx.com/{url_key}" if url_key else ""
            
            # Extract image
            media = item.get("media", {})
            image_url = ""
            if "imageUrl" in media:
                image_url = media["imageUrl"]
            elif "thumbUrl" in media:
                image_url = media["thumbUrl"]
            
            # Extract SKU
            sku = item.get("styleId", "") or item.get("sku", "")
            
            # Parse name for brand, model, colorway
            brand_parsed, model, colorway = self._parse_product_name(name)
            if not brand:
                brand = brand_parsed
            
            # Create product
            product = SneakerProduct(
                name=self._normalize_product_name(name),
                brand=brand,
                model=model,
                colorway=colorway,
                sku=sku,
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=current_price,
                is_in_stock=current_price > 0,  # Has price = available
                sizes_available=[]  # Will be populated when getting detailed info
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create StockX product from API item: {e}")
            return None
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed StockX product information"""
        try:
            # Extract product slug from URL
            url_slug = product_url.split("/")[-1] if "/" in product_url else product_url
            
            # Get product details from API
            api_url = f"{self.api_url}/products/{url_slug}"
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._create_product_from_details(data, product_url)
                    else:
                        logger.warning(f"StockX product details failed with status {response.status}")
                        return await self._fallback_product_scraping(product_url)
        
        except Exception as e:
            logger.error(f"Failed to get StockX product details for {product_url}: {e}")
            return await self._fallback_product_scraping(product_url)
    
    async def _create_product_from_details(self, data: Dict, product_url: str) -> Optional[SneakerProduct]:
        """Create detailed product from StockX API response"""
        try:
            product_data = data.get("Product", data)
            
            name = product_data.get("title", "")
            brand = product_data.get("brand", "")
            sku = product_data.get("styleId", "")
            
            # Get market data
            market = product_data.get("market", {})
            current_price = market.get("lowestAsk", 0)
            
            # Get image
            media = product_data.get("media", {})
            image_url = media.get("imageUrl", "")
            
            # Get size data
            variants = product_data.get("variants", [])
            sizes_available = []
            
            for variant in variants:
                if variant.get("hidden") or not variant.get("market", {}).get("lowestAsk"):
                    continue
                
                size_info = variant.get("size", "")
                if size_info:
                    try:
                        # Extract US size
                        us_size = float(size_info.replace("US ", "").replace("M", "").strip())
                        sizes_available.append(SneakerSize(us_size=us_size))
                    except ValueError:
                        continue
            
            # Parse name
            brand_parsed, model, colorway = self._parse_product_name(name)
            if not brand:
                brand = brand_parsed
            
            product = SneakerProduct(
                name=self._normalize_product_name(name),
                brand=brand,
                model=model,
                colorway=colorway,
                sku=sku,
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=current_price,
                is_in_stock=current_price > 0,
                sizes_available=sizes_available
            )
            
            return product
            
        except Exception as e:
            logger.error(f"Failed to create detailed StockX product: {e}")
            return None
    
    async def get_market_data(self, product_url: str) -> List[ResellData]:
        """Get market/resell data for a product"""
        resell_data = []
        
        try:
            url_slug = product_url.split("/")[-1] if "/" in product_url else product_url
            
            # Get sales history from API
            sales_url = f"{self.api_url}/products/{url_slug}/activity"
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.get(sales_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        resell_data = await self._parse_sales_data(data, product_url)
        
        except Exception as e:
            logger.error(f"Failed to get StockX market data for {product_url}: {e}")
        
        return resell_data
    
    async def _parse_sales_data(self, data: Dict, product_url: str) -> List[ResellData]:
        """Parse sales data from StockX API"""
        resell_data = []
        
        try:
            # Parse sales activity
            activities = data.get("ProductActivity", [])
            
            for activity in activities[:10]:  # Last 10 sales
                if activity.get("chainId") != "sales":
                    continue
                
                # Extract sale info
                amount = activity.get("amount", 0)
                size_info = activity.get("size", "")
                sale_date = activity.get("createdAt", "")
                
                if amount > 0 and size_info:
                    try:
                        # Parse size
                        us_size = float(size_info.replace("US ", "").replace("M", "").strip())
                        
                        # Parse date
                        from datetime import datetime
                        sale_datetime = datetime.fromisoformat(sale_date.replace("Z", "+00:00"))
                        
                        # Extract product name from URL
                        product_name = product_url.split("/")[-1].replace("-", " ").title()
                        
                        resell_item = ResellData(
                            sneaker_name=product_name,
                            size=SneakerSize(us_size=us_size),
                            platform="stockx",
                            price=amount,
                            last_sale_date=sale_datetime
                        )
                        
                        resell_data.append(resell_item)
                        
                    except (ValueError, TypeError) as e:
                        continue
        
        except Exception as e:
            logger.error(f"Failed to parse StockX sales data: {e}")
        
        return resell_data
    
    async def _fallback_web_scraping(self, keyword: str) -> List[SneakerProduct]:
        """Fallback web scraping when API fails"""
        products = []
        
        try:
            search_url = f"https://stockx.com/search?s={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                return products
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Parse product cards from HTML
            product_items = soup.find_all("div", {"data-testid": "ProductItem"})
            
            for item in product_items:
                try:
                    # Extract product info from HTML
                    link_elem = item.find("a")
                    if not link_elem:
                        continue
                    
                    product_url = "https://stockx.com" + link_elem.get("href", "")
                    
                    # Extract name
                    name_elem = item.find("p", {"data-testid": "ProductName"})
                    name = name_elem.get_text(strip=True) if name_elem else ""
                    
                    # Extract price
                    price_elem = item.find("p", {"data-testid": "ProductPrice"})
                    price_text = price_elem.get_text(strip=True) if price_elem else ""
                    price = self._extract_price(price_text)
                    
                    # Extract image
                    img_elem = item.find("img")
                    image_url = img_elem.get("src", "") if img_elem else ""
                    
                    if name:
                        brand, model, colorway = self._parse_product_name(name)
                        
                        product = SneakerProduct(
                            name=self._normalize_product_name(name),
                            brand=brand,
                            model=model,
                            colorway=colorway,
                            sku="",
                            retailer=self.retailer,
                            url=product_url,
                            image_url=image_url,
                            price=price,
                            is_in_stock=price is not None and price > 0
                        )
                        
                        products.append(product)
                
                except Exception as e:
                    logger.warning(f"Failed to parse StockX product item: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"StockX fallback web scraping failed: {e}")
        
        return products
    
    async def _fallback_product_scraping(self, product_url: str) -> Optional[SneakerProduct]:
        """Fallback product scraping when API fails"""
        try:
            response = await self._make_request(product_url)
            if not response:
                return None
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract product data from HTML
            name_elem = soup.find("h1", {"data-testid": "ProductPageTitle"})
            name = name_elem.get_text(strip=True) if name_elem else ""
            
            price_elem = soup.find("p", {"data-testid": "ProductPageLowestAsk"})
            price_text = price_elem.get_text(strip=True) if price_elem else ""
            price = self._extract_price(price_text)
            
            if name:
                brand, model, colorway = self._parse_product_name(name)
                
                return SneakerProduct(
                    name=self._normalize_product_name(name),
                    brand=brand,
                    model=model,
                    colorway=colorway,
                    sku="",
                    retailer=self.retailer,
                    url=product_url,
                    price=price,
                    is_in_stock=price is not None and price > 0
                )
        
        except Exception as e:
            logger.error(f"StockX fallback product scraping failed: {e}")
        
        return None
    
    def _parse_product_name(self, name: str) -> tuple[str, str, str]:
        """Parse StockX product name into brand, model, and colorway"""
        if not name:
            return "", "", ""
        
        name_lower = name.lower()
        
        # Determine brand
        if "jordan" in name_lower or "air jordan" in name_lower:
            brand = "Jordan"
        elif "nike" in name_lower:
            brand = "Nike"
        elif "adidas" in name_lower or "yeezy" in name_lower:
            brand = "Adidas"
        elif "new balance" in name_lower:
            brand = "New Balance"
        else:
            # Try to extract brand from first word
            parts = name.split()
            brand = parts[0] if parts else ""
        
        # Extract model and colorway
        parts = name.split()
        
        if "jordan" in name_lower:
            # Jordan pattern
            if len(parts) >= 3:
                model = " ".join(parts[:3])
                colorway = " ".join(parts[3:])
            else:
                model = " ".join(parts[:2])
                colorway = ""
        elif "yeezy" in name_lower:
            # Yeezy pattern
            if len(parts) >= 4:
                model = " ".join(parts[:4])
                colorway = " ".join(parts[4:])
            else:
                model = " ".join(parts[:3])
                colorway = ""
        else:
            # Generic pattern
            if len(parts) >= 3:
                model = " ".join(parts[:3])
                colorway = " ".join(parts[3:])
            else:
                model = " ".join(parts[:2]) if len(parts) >= 2 else parts[0] if parts else ""
                colorway = ""
        
        return brand, model, colorway
