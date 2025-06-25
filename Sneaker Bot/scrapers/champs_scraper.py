"""
Champs Sports scraper with API integration
"""
import json
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus, urljoin
import aiohttp
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.base_scraper import BaseScraper


class ChampsScraper(BaseScraper):
    """Champs Sports scraper with API integration"""
    
    def __init__(self):
        super().__init__(Retailer.FINISH_LINE)  # Using FINISH_LINE as enum placeholder
        self.base_url = "https://www.champssports.com"
        self.api_url = "https://www.champssports.com/api"
        self.search_endpoint = "https://www.champssports.com/on/demandware.store/Sites-ChampsSports-Site/en_US/Search-UpdateGrid"
        
        # API headers
        self.api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.champssports.com/",
            "Origin": "https://www.champssports.com",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search Champs Sports for products"""
        products = []
        
        try:
            # Try API search first
            products = await self._search_api(keyword)
            
            if not products:
                # Fallback to web scraping
                products = await self._fallback_web_scraping(keyword)
            
            logger.info(f"Champs Sports search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"Champs Sports search failed for '{keyword}': {e}")
        
        return products
    
    async def _search_api(self, keyword: str) -> List[SneakerProduct]:
        """Search using Champs Sports API"""
        products = []
        
        try:
            # Champs uses Demandware platform like FootLocker
            search_params = {
                "q": keyword,
                "cgid": "mens-shoes",
                "srule": "best-matches",
                "start": 0,
                "sz": 24,
                "format": "ajax"
            }
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.get(self.search_endpoint, params=search_params) as response:
                    if response.status == 200:
                        # Try to parse as JSON first
                        content_type = response.headers.get('content-type', '')
                        
                        if 'application/json' in content_type:
                            data = await response.json()
                            products = await self._parse_search_response(data)
                        else:
                            # Parse HTML response
                            html = await response.text()
                            products = await self._parse_search_html(html)
                    else:
                        logger.warning(f"Champs API failed with status {response.status}")
        
        except Exception as e:
            logger.error(f"Champs API search failed: {e}")
        
        return products
    
    async def _parse_search_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse Champs API search response"""
        products = []
        
        try:
            # Handle different response formats
            product_list = []
            
            if "products" in data:
                product_list = data["products"]
            elif "hits" in data:
                product_list = data["hits"]
            elif "searchResults" in data and "products" in data["searchResults"]:
                product_list = data["searchResults"]["products"]
            
            for item in product_list:
                product = await self._create_product_from_api_item(item)
                if product:
                    products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse Champs search response: {e}")
        
        return products
    
    async def _create_product_from_api_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from Champs API item"""
        try:
            # Extract basic info
            name = item.get("productName", "") or item.get("name", "") or item.get("title", "")
            brand = item.get("brand", "") or item.get("brandName", "")
            sku = item.get("id", "") or item.get("productId", "") or item.get("masterId", "")
            
            # Extract pricing
            price = None
            price_info = item.get("price", {})
            
            if isinstance(price_info, dict):
                # Try different price fields
                price = (price_info.get("sales", {}).get("value") or 
                        price_info.get("list", {}).get("value") or 
                        price_info.get("current"))
            elif isinstance(price_info, (int, float)):
                price = float(price_info)
            
            # Try alternative price fields
            if not price:
                price = (item.get("salePrice") or 
                        item.get("listPrice") or 
                        item.get("currentPrice"))
            
            # Extract URL
            product_url = ""
            if "url" in item:
                product_url = urljoin(self.base_url, item["url"])
            elif "pdpURL" in item:
                product_url = urljoin(self.base_url, item["pdpURL"])
            elif "link" in item:
                product_url = urljoin(self.base_url, item["link"])
            
            # Extract image
            image_url = ""
            images = item.get("images", {})
            
            if isinstance(images, dict):
                # Try different image sizes
                image_url = (images.get("large", [{}])[0].get("url", "") or 
                           images.get("medium", [{}])[0].get("url", "") or 
                           images.get("small", [{}])[0].get("url", ""))
            elif isinstance(images, list) and images:
                if isinstance(images[0], dict):
                    image_url = images[0].get("url", "")
                else:
                    image_url = str(images[0])
            
            # Try alternative image fields
            if not image_url:
                image_url = item.get("imageUrl", "") or item.get("thumbnail", "")
            
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.base_url, image_url)
            
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
                sku=str(sku),
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=float(price) if price and float(price) > 0 else None,
                is_in_stock=True,  # Assume in stock if returned from search
                sizes_available=[]
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create Champs product from API item: {e}")
            return None
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed Champs product information"""
        try:
            # Extract product ID from URL
            url_parts = product_url.split("/")
            product_id = ""
            
            # Find product ID in URL
            for part in reversed(url_parts):
                if part and (part.replace("-", "").replace("_", "").isalnum()):
                    product_id = part
                    break
            
            if not product_id:
                return await self._fallback_product_scraping(product_url)
            
            # Try API endpoints for product details
            api_endpoints = [
                f"{self.base_url}/on/demandware.store/Sites-ChampsSports-Site/en_US/Product-Variation",
                f"{self.api_url}/products/{product_id}",
                f"{self.base_url}/api/product/{product_id}"
            ]
            
            for api_url in api_endpoints:
                try:
                    params = {"pid": product_id, "Quantity": 1}
                    
                    async with aiohttp.ClientSession(headers=self.api_headers) as session:
                        async with session.get(api_url, params=params) as response:
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
            logger.error(f"Failed to get Champs product details for {product_url}: {e}")
            return await self._fallback_product_scraping(product_url)
    
    async def _create_detailed_product(self, data: Dict, product_url: str) -> Optional[SneakerProduct]:
        """Create detailed product from Champs API response"""
        try:
            product_data = data.get("product", data)
            
            name = (product_data.get("productName") or 
                   product_data.get("name") or 
                   product_data.get("title", ""))
            
            brand = (product_data.get("brand") or 
                    product_data.get("brandName", ""))
            
            sku = (product_data.get("id") or 
                  product_data.get("masterId") or 
                  product_data.get("productId", ""))
            
            # Get pricing
            price = None
            price_info = product_data.get("price", {})
            if isinstance(price_info, dict):
                price = (price_info.get("sales", {}).get("value") or 
                        price_info.get("list", {}).get("value"))
            
            # Get image
            image_url = ""
            images = product_data.get("images", {})
            if isinstance(images, dict) and "large" in images:
                if images["large"]:
                    image_url = images["large"][0].get("url", "")
            
            # Get size/variant data
            sizes_available = []
            variants = product_data.get("variationAttributes", [])
            
            for variant in variants:
                if variant.get("id") == "size":
                    for size_option in variant.get("values", []):
                        size_value = size_option.get("value", "")
                        is_available = size_option.get("selectable", True)
                        
                        if size_value and is_available:
                            try:
                                us_size = self._parse_size(size_value)
                                if us_size:
                                    sizes_available.append(SneakerSize(us_size=us_size))
                            except ValueError:
                                continue
            
            # Parse name
            brand_parsed, model, colorway = self._parse_product_name(name, brand)
            if not brand:
                brand = brand_parsed
            
            product = SneakerProduct(
                name=self._normalize_product_name(name),
                brand=brand,
                model=model,
                colorway=colorway,
                sku=str(sku),
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=float(price) if price else None,
                is_in_stock=len(sizes_available) > 0,
                sizes_available=sizes_available
            )
            
            return product
            
        except Exception as e:
            logger.error(f"Failed to create detailed Champs product: {e}")
            return None
    
    def _parse_size(self, size_str: str) -> Optional[float]:
        """Parse size string to US size float"""
        try:
            # Handle different size formats
            size_str = size_str.strip().upper()
            
            # Remove common prefixes/suffixes
            size_str = size_str.replace("US", "").replace("SIZE", "").replace("M", "").replace("W", "").strip()
            
            # Extract number
            import re
            size_match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if size_match:
                return float(size_match.group(1))
        
        except ValueError:
            pass
        
        return None
    
    async def _parse_search_html(self, html: str) -> List[SneakerProduct]:
        """Parse search results from HTML response"""
        products = []
        
        try:
            soup = await self._parse_html(html)
            
            # Look for product data in script tags or product tiles
            product_tiles = soup.find_all("div", class_=lambda x: x and any(term in x.lower() for term in ["product", "tile", "item"]))
            
            for tile in product_tiles:
                try:
                    # Extract product link
                    link_elem = tile.find("a", href=True)
                    if not link_elem:
                        continue
                    
                    product_url = urljoin(self.base_url, link_elem["href"])
                    
                    # Extract product name
                    name_elem = tile.find(["h2", "h3", "h4", "span"], class_=lambda x: x and any(term in x.lower() for term in ["name", "title"]))
                    name = name_elem.get_text(strip=True) if name_elem else ""
                    
                    # Extract price
                    price_elem = tile.find(["span", "div"], class_=lambda x: x and "price" in x.lower())
                    price = None
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        price = self._extract_price(price_text)
                    
                    # Extract image
                    img_elem = tile.find("img")
                    image_url = ""
                    if img_elem:
                        image_url = img_elem.get("src", "") or img_elem.get("data-src", "")
                        if image_url and not image_url.startswith("http"):
                            image_url = urljoin(self.base_url, image_url)
                    
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
                    logger.warning(f"Failed to parse Champs product tile: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Failed to parse Champs search HTML: {e}")
        
        return products
    
    async def _fallback_web_scraping(self, keyword: str) -> List[SneakerProduct]:
        """Fallback web scraping when API fails"""
        products = []
        
        try:
            search_url = f"{self.base_url}/search?q={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                return products
            
            html = await response.text()
            products = await self._parse_search_html(html)
        
        except Exception as e:
            logger.error(f"Champs fallback web scraping failed: {e}")
        
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
                        brand = data.get("brand", {}).get("name", "") if isinstance(data.get("brand"), dict) else data.get("brand", "")
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
            name_elem = soup.find("h1") or soup.find(class_=lambda x: x and "product" in x.lower() and "name" in x.lower())
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
            logger.error(f"Champs fallback product scraping failed: {e}")
        
        return None
    
    def _parse_product_name(self, name: str, brand: str = "") -> tuple[str, str, str]:
        """Parse Champs product name into brand, model, and colorway"""
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
            elif "under armour" in name_lower:
                brand = "Under Armour"
            else:
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