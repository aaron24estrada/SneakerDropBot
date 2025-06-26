"""
FootLocker scraper with internal API integration
"""
import json
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus, urljoin
import aiohttp
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.base_scraper import BaseScraper


class FootLockerScraper(BaseScraper):
    """FootLocker scraper with internal API integration"""
    
    def __init__(self):
        super().__init__(Retailer.FOOTLOCKER)
        self.base_url = "https://www.footlocker.com"
        self.api_url = "https://www.footlocker.com/api"
        self.search_api = "https://www.footlocker.com/api/products/search"
        
        # API headers (mimicking FootLocker web requests)
        self.api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.footlocker.com/",
            "Origin": "https://www.footlocker.com",
            "Content-Type": "application/json",
            "X-API-Key": "m3bvdm73YY7H6FBeaTqD94eFZdJQeNnA",  # Public API key from web app
            "X-API-Lang": "en-US",
            "X-API-Country": "US",
            "X-Customer-Type": "guest",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search FootLocker for products"""
        products = []
        
        try:
            # Try internal API first
            products = await self._search_internal_api(keyword)
            
            if not products:
                # Fallback to web scraping
                products = await self._fallback_web_scraping(keyword)
            
            logger.info(f"FootLocker search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"FootLocker search failed for '{keyword}': {e}")
        
        return products
    
    async def _search_internal_api(self, keyword: str) -> List[SneakerProduct]:
        """Search using FootLocker internal API"""
        products = []
        
        try:
            # Search parameters
            search_params = {
                "query": keyword,
                "filter": "category:mens-shoes,womens-shoes",
                "sort": "relevance",
                "limit": 24,
                "offset": 0,
                "facets": "category,brand,price,size",
                "locale": "en-US"
            }
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.get(self.search_api, params=search_params) as response:
                    if response.status == 200:
                        data = await response.json()
                        products = await self._parse_search_response(data)
                    else:
                        logger.warning(f"FootLocker API failed with status {response.status}")
        
        except Exception as e:
            logger.error(f"FootLocker internal API search failed: {e}")
        
        return products
    
    async def _parse_search_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse FootLocker API search response"""
        products = []
        
        try:
            # Parse the response structure
            if "products" in data:
                for item in data["products"]:
                    product = await self._create_product_from_api_item(item)
                    if product:
                        products.append(product)
            elif "results" in data:
                for item in data["results"]:
                    product = await self._create_product_from_api_item(item)
                    if product:
                        products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse FootLocker search response: {e}")
        
        return products
    
    async def _create_product_from_api_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from FootLocker API item"""
        try:
            # Extract basic info
            name = item.get("name", "") or item.get("title", "")
            brand = item.get("brand", "") or item.get("brandName", "")
            sku = item.get("sku", "") or item.get("productId", "")
            
            # Extract pricing
            price_info = item.get("price", {})
            if isinstance(price_info, dict):
                current_price = price_info.get("current", 0) or price_info.get("sale", 0) or price_info.get("regular", 0)
            else:
                current_price = float(price_info) if price_info else 0
            
            # Extract URL
            product_url = ""
            if "url" in item:
                product_url = urljoin(self.base_url, item["url"])
            elif "pdpUrl" in item:
                product_url = urljoin(self.base_url, item["pdpUrl"])
            elif "slug" in item:
                product_url = f"{self.base_url}/product/{item['slug']}"
            
            # Extract image
            image_url = ""
            images = item.get("images", [])
            if images and isinstance(images, list):
                image_url = images[0].get("url", "") if isinstance(images[0], dict) else str(images[0])
            elif "imageUrl" in item:
                image_url = item["imageUrl"]
            elif "thumbnail" in item:
                image_url = item["thumbnail"]
            
            # Extract availability
            is_in_stock = True
            if "inventory" in item:
                inventory = item["inventory"]
                if isinstance(inventory, dict):
                    is_in_stock = inventory.get("available", True)
                else:
                    is_in_stock = bool(inventory)
            elif "isAvailable" in item:
                is_in_stock = item["isAvailable"]
            
            # Parse name for brand, model, colorway
            brand_parsed, model, colorway = self._parse_product_name(name, brand)
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
                price=current_price if current_price > 0 else None,
                is_in_stock=is_in_stock,
                sizes_available=[]  # Will be populated in detailed view
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create FootLocker product from API item: {e}")
            return None
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed FootLocker product information"""
        try:
            # Extract product identifier from URL
            url_parts = product_url.split("/")
            product_id = url_parts[-1] if url_parts else ""
            
            # Try different API endpoints
            api_endpoints = [
                f"{self.api_url}/products/{product_id}",
                f"{self.api_url}/product/{product_id}",
                f"{self.api_url}/products/details/{product_id}"
            ]
            
            for api_url in api_endpoints:
                try:
                    async with aiohttp.ClientSession(headers=self.api_headers) as session:
                        async with session.get(api_url) as response:
                            if response.status == 200:
                                data = await response.json()
                                product = await self._create_detailed_product(data, product_url)
                                if product:
                                    return product
                except Exception:
                    continue
            
            # Fallback to web scraping
            return await self._fallback_product_scraping(product_url)
        
        except Exception as e:
            logger.error(f"Failed to get FootLocker product details for {product_url}: {e}")
            return await self._fallback_product_scraping(product_url)
    
    async def _create_detailed_product(self, data: Dict, product_url: str) -> Optional[SneakerProduct]:
        """Create detailed product from FootLocker API response"""
        try:
            product_data = data.get("product", data)
            
            name = product_data.get("name", "") or product_data.get("title", "")
            brand = product_data.get("brand", "") or product_data.get("brandName", "")
            sku = product_data.get("sku", "") or product_data.get("productId", "")
            
            # Get pricing
            price_info = product_data.get("price", {})
            current_price = None
            if isinstance(price_info, dict):
                current_price = price_info.get("current") or price_info.get("sale") or price_info.get("regular")
            else:
                current_price = float(price_info) if price_info else None
            
            # Get image
            image_url = ""
            images = product_data.get("images", [])
            if images:
                if isinstance(images[0], dict):
                    image_url = images[0].get("url", "")
                else:
                    image_url = str(images[0])
            
            # Get size data
            sizes_available = []
            variants = product_data.get("variants", []) or product_data.get("sizes", [])
            
            for variant in variants:
                size_info = variant.get("size", "") or variant.get("value", "")
                is_available = variant.get("available", True) or variant.get("inStock", True)
                
                if size_info and is_available:
                    try:
                        us_size = self._parse_size(size_info)
                        if us_size:
                            sizes_available.append(SneakerSize(us_size=us_size))
                    except ValueError:
                        continue
            
            # Get availability
            is_in_stock = product_data.get("isAvailable", True)
            if "inventory" in product_data:
                inventory = product_data["inventory"]
                if isinstance(inventory, dict):
                    is_in_stock = inventory.get("available", True)
            
            # Parse name
            brand_parsed, model, colorway = self._parse_product_name(name, brand)
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
                is_in_stock=is_in_stock,
                sizes_available=sizes_available
            )
            
            return product
            
        except Exception as e:
            logger.error(f"Failed to create detailed FootLocker product: {e}")
            return None
    
    def _parse_size(self, size_str: str) -> Optional[float]:
        """Parse size string to US size float"""
        try:
            # Handle different size formats
            size_str = size_str.strip()
            
            # Remove common prefixes/suffixes
            size_str = size_str.replace("US", "").replace("Size", "").replace("M", "").replace("W", "").strip()
            
            # Extract number
            import re
            size_match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if size_match:
                return float(size_match.group(1))
        
        except ValueError:
            pass
        
        return None
    
    async def _fallback_web_scraping(self, keyword: str) -> List[SneakerProduct]:
        """Fallback web scraping when API fails"""
        products = []
        
        try:
            search_url = f"{self.base_url}/search?query={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                return products
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Look for product data in script tags
            scripts = soup.find_all("script", type="application/json")
            
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if "products" in data:
                        for item in data["products"]:
                            product = await self._create_product_from_api_item(item)
                            if product:
                                products.append(product)
                        break
                except json.JSONDecodeError:
                    continue
            
            # Fallback to HTML product cards
            if not products:
                products = await self._parse_product_cards(soup)
        
        except Exception as e:
            logger.error(f"FootLocker fallback web scraping failed: {e}")
        
        return products
    
    async def _parse_product_cards(self, soup) -> List[SneakerProduct]:
        """Parse product cards from FootLocker HTML"""
        products = []
        
        try:
            # Look for product tiles
            product_tiles = soup.find_all("div", class_=lambda x: x and "ProductTile" in x)
            
            if not product_tiles:
                # Alternative selectors
                product_tiles = soup.find_all("article", class_="product-tile")
            
            for tile in product_tiles:
                try:
                    # Extract product link
                    link_elem = tile.find("a", href=True)
                    if not link_elem:
                        continue
                    
                    product_url = urljoin(self.base_url, link_elem["href"])
                    
                    # Extract product name
                    name_elem = tile.find(["h3", "h4", "span"], class_=lambda x: x and any(term in x.lower() for term in ["name", "title", "product"]))
                    name = name_elem.get_text(strip=True) if name_elem else ""
                    
                    # Extract price
                    price_elem = tile.find(["span", "div"], class_=lambda x: x and "price" in x.lower())
                    price = None
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        price = self._extract_price(price_text)
                    
                    # Extract image
                    img_elem = tile.find("img")
                    image_url = img_elem.get("src", "") or img_elem.get("data-src", "") if img_elem else ""
                    
                    if name:
                        brand, model, colorway = self._parse_product_name(name, "")
                        
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
                            is_in_stock=price is not None
                        )
                        
                        products.append(product)
                
                except Exception as e:
                    logger.warning(f"Failed to parse FootLocker product tile: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Failed to parse FootLocker product cards: {e}")
        
        return products
    
    async def _fallback_product_scraping(self, product_url: str) -> Optional[SneakerProduct]:
        """Fallback product scraping when API fails"""
        try:
            response = await self._make_request(product_url)
            if not response:
                return None
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Look for structured data
            json_ld = soup.find("script", type="application/ld+json")
            if json_ld:
                try:
                    data = json.loads(json_ld.string)
                    if data.get("@type") == "Product":
                        name = data.get("name", "")
                        brand = data.get("brand", {}).get("name", "")
                        sku = data.get("sku", "")
                        
                        # Get price
                        offers = data.get("offers", {})
                        price = None
                        if "price" in offers:
                            price = float(offers["price"])
                        
                        # Get image
                        image_url = ""
                        if "image" in data:
                            image_list = data["image"]
                            if isinstance(image_list, list) and image_list:
                                image_url = image_list[0]
                            elif isinstance(image_list, str):
                                image_url = image_list
                        
                        # Parse name
                        brand_parsed, model, colorway = self._parse_product_name(name, brand)
                        
                        return SneakerProduct(
                            name=self._normalize_product_name(name),
                            brand=brand or brand_parsed,
                            model=model,
                            colorway=colorway,
                            sku=sku,
                            retailer=self.retailer,
                            url=product_url,
                            image_url=image_url,
                            price=price,
                            is_in_stock=price is not None
                        )
                
                except json.JSONDecodeError:
                    pass
            
            # Fallback to HTML parsing
            name_elem = soup.find("h1")
            name = name_elem.get_text(strip=True) if name_elem else ""
            
            if name:
                brand, model, colorway = self._parse_product_name(name, "")
                
                return SneakerProduct(
                    name=self._normalize_product_name(name),
                    brand=brand,
                    model=model,
                    colorway=colorway,
                    sku="",
                    retailer=self.retailer,
                    url=product_url,
                    is_in_stock=True
                )
        
        except Exception as e:
            logger.error(f"FootLocker fallback product scraping failed: {e}")
        
        return None
    
    def _parse_product_name(self, name: str, brand: str = "") -> tuple[str, str, str]:
        """Parse FootLocker product name into brand, model, and colorway"""
        if not name:
            return brand, "", ""
        
        name_lower = name.lower()
        
        # Use provided brand or determine from name
        if not brand:
            if "jordan" in name_lower:
                brand = "Jordan"
            elif "nike" in name_lower:
                brand = "Nike"
            elif "adidas" in name_lower:
                brand = "Adidas"
            elif "new balance" in name_lower:
                brand = "New Balance"
            elif "puma" in name_lower:
                brand = "Puma"
            elif "reebok" in name_lower:
                brand = "Reebok"
            elif "vans" in name_lower:
                brand = "Vans"
            elif "converse" in name_lower:
                brand = "Converse"
            else:
                parts = name.split()
                brand = parts[0] if parts else ""
        
        # Extract model and colorway
        parts = name.split()
        
        if "jordan" in name_lower:
            # Jordan pattern: "Jordan 1 Low Bred"
            if len(parts) >= 3:
                model = " ".join(parts[:3])
                colorway = " ".join(parts[3:])
            else:
                model = " ".join(parts[:2])
                colorway = ""
        elif any(term in name_lower for term in ["air max", "air force", "dunk"]):
            # Nike patterns
            if len(parts) >= 3:
                model = " ".join(parts[:3])
                colorway = " ".join(parts[3:])
            else:
                model = " ".join(parts[:2])
                colorway = ""
        else:
            # Generic pattern
            if len(parts) >= 2:
                model = " ".join(parts[:2])
                colorway = " ".join(parts[2:]) if len(parts) > 2 else ""
            else:
                model = parts[0] if parts else ""
                colorway = ""
        
        return brand, model, colorway
