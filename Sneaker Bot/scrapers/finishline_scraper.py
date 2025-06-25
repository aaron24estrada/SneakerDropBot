"""
Finish Line scraper with API integration
"""
import json
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus, urljoin
import aiohttp
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.base_scraper import BaseScraper


class FinishLineScraper(BaseScraper):
    """Finish Line scraper with API integration"""
    
    def __init__(self):
        super().__init__(Retailer.FINISH_LINE)
        self.base_url = "https://www.finishline.com"
        self.api_url = "https://www.finishline.com/store/browse/productDetailApi.jsp"
        self.search_api = "https://www.finishline.com/store/catalog/search.jsp"
        
        # API headers
        self.api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.finishline.com/",
            "Origin": "https://www.finishline.com",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search Finish Line for products"""
        products = []
        
        try:
            # Try API search
            products = await self._search_api(keyword)
            
            if not products:
                # Fallback to web scraping
                products = await self._fallback_web_scraping(keyword)
            
            logger.info(f"Finish Line search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"Finish Line search failed for '{keyword}': {e}")
        
        return products
    
    async def _search_api(self, keyword: str) -> List[SneakerProduct]:
        """Search using Finish Line API"""
        products = []
        
        try:
            # Search parameters
            search_data = {
                "Ntt": keyword,
                "Ntk": "All",
                "Ntx": "mode+matchallpartial",
                "D": "3049",
                "Nty": "1",
                "Nrpp": "24",
                "No": "0",
                "Nr": "AND(product.siteId:FL)",
                "format": "json"
            }
            
            async with aiohttp.ClientSession(headers=self.api_headers) as session:
                async with session.post(self.search_api, data=search_data) as response:
                    if response.status == 200:
                        # Try to parse as JSON
                        try:
                            data = await response.json()
                            products = await self._parse_search_response(data)
                        except:
                            # If not JSON, try to extract from HTML
                            html = await response.text()
                            products = await self._parse_search_html(html)
                    else:
                        logger.warning(f"Finish Line API failed with status {response.status}")
        
        except Exception as e:
            logger.error(f"Finish Line API search failed: {e}")
        
        return products
    
    async def _parse_search_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse Finish Line API search response"""
        products = []
        
        try:
            # Handle different response formats
            if "contents" in data:
                for content in data["contents"]:
                    if "mainContent" in content:
                        for record in content["mainContent"]:
                            if "records" in record:
                                for item in record["records"]:
                                    product = await self._create_product_from_api_item(item)
                                    if product:
                                        products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse Finish Line search response: {e}")
        
        return products
    
    async def _create_product_from_api_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from Finish Line API item"""
        try:
            # Extract attributes
            attributes = item.get("attributes", {})
            
            name = attributes.get("product.displayName", [""])[0]
            brand = attributes.get("product.brand", [""])[0]
            sku = attributes.get("product.repositoryId", [""])[0]
            
            # Extract pricing
            price = None
            price_list = attributes.get("sku.listPrice", [])
            sale_price_list = attributes.get("sku.salePrice", [])
            
            if sale_price_list and sale_price_list[0]:
                price = float(sale_price_list[0])
            elif price_list and price_list[0]:
                price = float(price_list[0])
            
            # Extract URL
            product_url = ""
            url_list = attributes.get("product.route", [])
            if url_list and url_list[0]:
                product_url = urljoin(self.base_url, url_list[0])
            
            # Extract image
            image_url = ""
            image_list = attributes.get("product.primaryImageUrl", [])
            if image_list and image_list[0]:
                image_url = image_list[0]
                if not image_url.startswith("http"):
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
                sku=sku,
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=price,
                is_in_stock=price is not None,
                sizes_available=[]
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create Finish Line product from API item: {e}")
            return None
    
    async def _parse_search_html(self, html: str) -> List[SneakerProduct]:
        """Parse search results from HTML response"""
        products = []
        
        try:
            soup = await self._parse_html(html)
            
            # Look for product data in script tags
            scripts = soup.find_all("script")
            
            for script in scripts:
                if script.string and "productData" in script.string:
                    try:
                        # Extract JSON data from script
                        script_content = script.string
                        start = script_content.find("productData")
                        if start != -1:
                            # Find the JSON object
                            json_start = script_content.find("{", start)
                            json_end = script_content.find("};", json_start) + 1
                            
                            if json_start != -1 and json_end != -1:
                                json_str = script_content[json_start:json_end]
                                data = json.loads(json_str)
                                
                                if "products" in data:
                                    for item in data["products"]:
                                        product = await self._create_product_from_html_data(item)
                                        if product:
                                            products.append(product)
                    except (json.JSONDecodeError, ValueError):
                        continue
        
        except Exception as e:
            logger.error(f"Failed to parse Finish Line search HTML: {e}")
        
        return products
    
    async def _create_product_from_html_data(self, item: Dict) -> Optional[SneakerProduct]:
        """Create product from HTML embedded data"""
        try:
            name = item.get("name", "")
            brand = item.get("brand", "")
            sku = item.get("id", "") or item.get("sku", "")
            
            # Extract price
            price = item.get("price") or item.get("salePrice") or item.get("listPrice")
            if price:
                price = float(price)
            
            # Extract URL
            product_url = item.get("url", "")
            if product_url and not product_url.startswith("http"):
                product_url = urljoin(self.base_url, product_url)
            
            # Extract image
            image_url = item.get("image", "") or item.get("imageUrl", "")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.base_url, image_url)
            
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
                price=price,
                is_in_stock=price is not None,
                sizes_available=[]
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create Finish Line product from HTML data: {e}")
            return None
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed Finish Line product information"""
        try:
            # Extract product ID from URL
            url_parts = product_url.split("/")
            product_id = ""
            
            # Look for product ID patterns
            for part in url_parts:
                if part.startswith("_-_") or part.isdigit():
                    product_id = part
                    break
            
            if product_id:
                # Try API for product details
                api_data = {
                    "productId": product_id,
                    "format": "json"
                }
                
                async with aiohttp.ClientSession(headers=self.api_headers) as session:
                    async with session.post(self.api_url, data=api_data) as response:
                        if response.status == 200:
                            try:
                                data = await response.json()
                                product = await self._create_detailed_product(data, product_url)
                                if product:
                                    return product
                            except:
                                pass
            
            # Fallback to web scraping
            return await self._fallback_product_scraping(product_url)
        
        except Exception as e:
            logger.error(f"Failed to get Finish Line product details for {product_url}: {e}")
            return await self._fallback_product_scraping(product_url)
    
    async def _create_detailed_product(self, data: Dict, product_url: str) -> Optional[SneakerProduct]:
        """Create detailed product from Finish Line API response"""
        try:
            product_data = data.get("product", data)
            
            name = product_data.get("displayName", "") or product_data.get("name", "")
            brand = product_data.get("brand", "")
            sku = product_data.get("id", "") or product_data.get("repositoryId", "")
            
            # Get pricing
            price = None
            skus = product_data.get("childSKUs", [])
            if skus:
                first_sku = skus[0]
                price = first_sku.get("salePrice") or first_sku.get("listPrice")
                if price:
                    price = float(price)
            
            # Get image
            image_url = product_data.get("primaryImageUrl", "")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.base_url, image_url)
            
            # Get size data
            sizes_available = []
            for sku_item in skus:
                size_info = sku_item.get("size", "")
                is_available = sku_item.get("inventoryStatus") == "IN_STOCK"
                
                if size_info and is_available:
                    try:
                        us_size = self._parse_size(size_info)
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
                sku=sku,
                retailer=self.retailer,
                url=product_url,
                image_url=image_url,
                price=price,
                is_in_stock=len(sizes_available) > 0,
                sizes_available=sizes_available
            )
            
            return product
            
        except Exception as e:
            logger.error(f"Failed to create detailed Finish Line product: {e}")
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
            search_url = f"{self.base_url}/store/browse/search.jsp?Ntt={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                return products
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Look for product tiles
            product_tiles = soup.find_all(["div", "article"], class_=lambda x: x and any(term in x.lower() for term in ["product", "tile", "item"]))
            
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
                    logger.warning(f"Failed to parse Finish Line product tile: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Finish Line fallback web scraping failed: {e}")
        
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
            logger.error(f"Finish Line fallback product scraping failed: {e}")
        
        return None
    
    def _parse_product_name(self, name: str, brand: str = "") -> tuple[str, str, str]:
        """Parse Finish Line product name into brand, model, and colorway"""
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
