"""
GOAT scraper with mobile API integration
"""
import json
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus
import aiohttp
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer, ResellData
from scrapers.base_scraper import BaseScraper


class GOATScraper(BaseScraper):
    """GOAT scraper with mobile API integration"""
    
    def __init__(self):
        super().__init__(Retailer.GOAT)
        self.base_url = "https://www.goat.com"
        self.api_url = "https://2fwotdvm2o-dsn.algolia.net/1/indexes/product_variants_v2"
        self.mobile_api_url = "https://ac.cnstrc.com/search"
        
        # Mobile API headers (mimicking GOAT mobile app)
        self.mobile_headers = {
            "User-Agent": "GOAT/2.64.1 (iPhone; iOS 17.0; Scale/3.00)",
            "Accept": "application/json",
            "Accept-Language": "en-US;q=1.0",
            "Authorization": "Bearer goat-mobile-app",
            "Content-Type": "application/json",
            "X-API-Version": "2",
            "X-Platform": "ios"
        }
        
        # Web API headers
        self.web_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.goat.com/",
            "Origin": "https://www.goat.com",
            "X-Algolia-API-Key": "ac96de6fef0e02bb95d433d8d5c7038a",
            "X-Algolia-Application-Id": "2FWOTDVM2O"
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search GOAT for products"""
        products = []
        
        try:
            # Try mobile API first
            products = await self._search_mobile_api(keyword)
            
            if not products:
                # Fallback to web API
                products = await self._search_web_api(keyword)
            
            if not products:
                # Final fallback to web scraping
                products = await self._fallback_web_scraping(keyword)
            
            logger.info(f"GOAT search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"GOAT search failed for '{keyword}': {e}")
        
        return products
    
    async def _search_mobile_api(self, keyword: str) -> List[SneakerProduct]:
        """Search using GOAT mobile API"""
        products = []
        
        try:
            # Mobile API search endpoint
            search_url = "https://www.goat.com/api/v1/search"
            
            params = {
                "query": keyword,
                "category": "shoes",
                "filters": json.dumps({"category": ["shoes"]}),
                "sort": "relevance",
                "limit": 20,
                "offset": 0
            }
            
            async with aiohttp.ClientSession(headers=self.mobile_headers) as session:
                async with session.get(search_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        products = await self._parse_mobile_response(data)
                    else:
                        logger.warning(f"GOAT mobile API failed with status {response.status}")
            
        except Exception as e:
            logger.error(f"GOAT mobile API search failed: {e}")
        
        return products
    
    async def _search_web_api(self, keyword: str) -> List[SneakerProduct]:
        """Search using GOAT web API (Algolia)"""
        products = []
        
        try:
            # Algolia search parameters
            search_params = {
                "query": keyword,
                "hitsPerPage": 20,
                "page": 0,
                "filters": "status:active AND category:shoes",
                "facetFilters": [["category:shoes"]],
                "attributesToRetrieve": "*",
                "attributesToHighlight": "[]"
            }
            
            async with aiohttp.ClientSession(headers=self.web_headers) as session:
                async with session.post(self.api_url + "/query", json=search_params) as response:
                    if response.status == 200:
                        data = await response.json()
                        products = await self._parse_algolia_response(data)
                    else:
                        logger.warning(f"GOAT Algolia API failed with status {response.status}")
        
        except Exception as e:
            logger.error(f"GOAT Algolia API search failed: {e}")
        
        return products
    
    async def _parse_mobile_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse GOAT mobile API response"""
        products = []
        
        try:
            results = data.get("results", [])
            
            for item in results:
                product = await self._create_product_from_mobile_item(item)
                if product:
                    products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse GOAT mobile response: {e}")
        
        return products
    
    async def _parse_algolia_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse GOAT Algolia API response"""
        products = []
        
        try:
            hits = data.get("hits", [])
            
            for item in hits:
                product = await self._create_product_from_algolia_item(item)
                if product:
                    products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to parse GOAT Algolia response: {e}")
        
        return products
    
    async def _create_product_from_mobile_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create product from GOAT mobile API item"""
        try:
            name = item.get("name", "")
            brand_name = item.get("brand_name", "")
            sku = item.get("sku", "")
            
            # Extract pricing
            price_cents = item.get("lowest_price_cents", 0)
            current_price = price_cents / 100 if price_cents > 0 else None
            
            # Extract URL
            slug = item.get("slug", "")
            product_url = f"https://www.goat.com/sneakers/{slug}" if slug else ""
            
            # Extract image
            image_url = item.get("main_picture_url", "")
            
            # Extract condition
            condition = item.get("condition", "new")
            is_new = condition.lower() in ["new", "brand new"]
            
            # Parse name
            brand, model, colorway = self._parse_product_name(name, brand_name)
            
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
                is_in_stock=current_price is not None,
                sizes_available=[]  # Will be populated in details
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create GOAT product from mobile item: {e}")
            return None
    
    async def _create_product_from_algolia_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create product from GOAT Algolia item"""
        try:
            name = item.get("name", "")
            brand_name = item.get("brand_name", "")
            sku = item.get("sku", "")
            
            # Extract pricing
            price_cents = item.get("lowest_price_cents_usd", 0) or item.get("retail_price_cents", 0)
            current_price = price_cents / 100 if price_cents > 0 else None
            
            # Extract URL
            slug = item.get("slug", "")
            product_url = f"https://www.goat.com/sneakers/{slug}" if slug else ""
            
            # Extract image
            image_url = item.get("picture_url", "") or item.get("main_picture_url", "")
            
            # Parse name
            brand, model, colorway = self._parse_product_name(name, brand_name)
            
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
                is_in_stock=current_price is not None,
                sizes_available=[]
            )
            
            return product
            
        except Exception as e:
            logger.warning(f"Failed to create GOAT product from Algolia item: {e}")
            return None
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed GOAT product information"""
        try:
            # Extract product slug from URL
            url_parts = product_url.split("/")
            slug = url_parts[-1] if url_parts else ""
            
            # Get product details from API
            api_url = f"https://www.goat.com/api/v1/products/{slug}"
            
            async with aiohttp.ClientSession(headers=self.mobile_headers) as session:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._create_detailed_product(data, product_url)
                    else:
                        logger.warning(f"GOAT product details failed with status {response.status}")
                        return await self._fallback_product_scraping(product_url)
        
        except Exception as e:
            logger.error(f"Failed to get GOAT product details for {product_url}: {e}")
            return await self._fallback_product_scraping(product_url)
    
    async def _create_detailed_product(self, data: Dict, product_url: str) -> Optional[SneakerProduct]:
        """Create detailed product from GOAT API response"""
        try:
            product_data = data.get("product", data)
            
            name = product_data.get("name", "")
            brand_name = product_data.get("brand_name", "")
            sku = product_data.get("sku", "")
            
            # Get pricing
            current_price = None
            if "lowest_price_cents" in product_data:
                current_price = product_data["lowest_price_cents"] / 100
            elif "retail_price_cents" in product_data:
                current_price = product_data["retail_price_cents"] / 100
            
            # Get image
            image_url = product_data.get("main_picture_url", "")
            
            # Get size data
            variants = product_data.get("product_template_variants", [])
            sizes_available = []
            
            for variant in variants:
                size_info = variant.get("size", "")
                if size_info and variant.get("lowest_price_cents", 0) > 0:
                    try:
                        # Parse US size
                        us_size = self._parse_size(size_info)
                        if us_size:
                            sizes_available.append(SneakerSize(us_size=us_size))
                    except ValueError:
                        continue
            
            # Parse name
            brand, model, colorway = self._parse_product_name(name, brand_name)
            
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
                is_in_stock=current_price is not None,
                sizes_available=sizes_available
            )
            
            return product
            
        except Exception as e:
            logger.error(f"Failed to create detailed GOAT product: {e}")
            return None
    
    def _parse_size(self, size_str: str) -> Optional[float]:
        """Parse size string to US size float"""
        try:
            # Handle different size formats
            size_str = size_str.strip().upper()
            
            # Remove prefixes
            size_str = size_str.replace("US ", "").replace("M ", "").replace("W ", "")
            
            # Extract number
            import re
            size_match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if size_match:
                return float(size_match.group(1))
        
        except ValueError:
            pass
        
        return None
    
    async def get_market_data(self, product_url: str) -> List[ResellData]:
        """Get market/resell data for a product"""
        resell_data = []
        
        try:
            url_parts = product_url.split("/")
            slug = url_parts[-1] if url_parts else ""
            
            # Get sales data from API
            sales_url = f"https://www.goat.com/api/v1/products/{slug}/sales"
            
            async with aiohttp.ClientSession(headers=self.mobile_headers) as session:
                async with session.get(sales_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        resell_data = await self._parse_sales_data(data, product_url)
        
        except Exception as e:
            logger.error(f"Failed to get GOAT market data for {product_url}: {e}")
        
        return resell_data
    
    async def _parse_sales_data(self, data: Dict, product_url: str) -> List[ResellData]:
        """Parse sales data from GOAT API"""
        resell_data = []
        
        try:
            sales = data.get("sales", [])
            
            for sale in sales[:10]:  # Last 10 sales
                price_cents = sale.get("amount_cents", 0)
                size_info = sale.get("size", "")
                sale_date = sale.get("sold_at", "")
                
                if price_cents > 0 and size_info:
                    try:
                        # Parse size
                        us_size = self._parse_size(size_info)
                        if not us_size:
                            continue
                        
                        # Parse date
                        from datetime import datetime
                        sale_datetime = datetime.fromisoformat(sale_date.replace("Z", "+00:00"))
                        
                        # Extract product name
                        product_name = product_url.split("/")[-1].replace("-", " ").title()
                        
                        resell_item = ResellData(
                            sneaker_name=product_name,
                            size=SneakerSize(us_size=us_size),
                            platform="goat",
                            price=price_cents / 100,
                            last_sale_date=sale_datetime
                        )
                        
                        resell_data.append(resell_item)
                        
                    except (ValueError, TypeError):
                        continue
        
        except Exception as e:
            logger.error(f"Failed to parse GOAT sales data: {e}")
        
        return resell_data
    
    async def _fallback_web_scraping(self, keyword: str) -> List[SneakerProduct]:
        """Fallback web scraping when APIs fail"""
        products = []
        
        try:
            search_url = f"https://www.goat.com/search?query={quote_plus(keyword)}"
            
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
                            product = await self._create_product_from_algolia_item(item)
                            if product:
                                products.append(product)
                        break
                except json.JSONDecodeError:
                    continue
        
        except Exception as e:
            logger.error(f"GOAT fallback web scraping failed: {e}")
        
        return products
    
    async def _fallback_product_scraping(self, product_url: str) -> Optional[SneakerProduct]:
        """Fallback product scraping when API fails"""
        try:
            response = await self._make_request(product_url)
            if not response:
                return None
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract JSON data from scripts
            scripts = soup.find_all("script", type="application/json")
            
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if "product" in data:
                        return await self._create_detailed_product(data, product_url)
                except json.JSONDecodeError:
                    continue
            
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
            logger.error(f"GOAT fallback product scraping failed: {e}")
        
        return None
    
    def _parse_product_name(self, name: str, brand_name: str = "") -> tuple[str, str, str]:
        """Parse GOAT product name into brand, model, and colorway"""
        if not name:
            return brand_name, "", ""
        
        name_lower = name.lower()
        
        # Use provided brand name or determine from product name
        brand = brand_name
        if not brand:
            if "jordan" in name_lower:
                brand = "Jordan"
            elif "nike" in name_lower:
                brand = "Nike"
            elif "adidas" in name_lower or "yeezy" in name_lower:
                brand = "Adidas"
            elif "new balance" in name_lower:
                brand = "New Balance"
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
