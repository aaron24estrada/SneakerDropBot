"""
Enhanced StockX scraper with multiple fallback strategies and API integration
"""
import json
import re
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus, urljoin
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer, ResellData
from scrapers.enhanced_base_scraper import EnhancedBaseScraper, ScrapingMethod, ScrapingResult


class EnhancedStockXScraper(EnhancedBaseScraper):
    """Enhanced StockX scraper with multiple API endpoints and fallback strategies"""
    
    def __init__(self):
        super().__init__(Retailer.STOCKX)
        self.base_url = "https://stockx.com"
        
        # Multiple StockX API endpoints
        self.api_endpoints = [
            {
                "name": "browse_api",
                "url": "https://stockx.com/api/browse",
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://stockx.com/",
                }
            },
            {
                "name": "search_api",
                "url": "https://stockx.com/api/search",
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": "StockX/1.0",
                    "X-Requested-With": "XMLHttpRequest",
                }
            },
            {
                "name": "public_api",
                "url": "https://stockx.com/api/products",
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; StockXBot/1.0)",
                }
            }
        ]
        
        # StockX-specific patterns for fallback parsing
        self.stockx_patterns = {
            "price_selectors": [
                "[data-testid='current-price']",
                ".current-price",
                ".bid-ask-price",
                "[class*='price-current']",
                ".price-value"
            ],
            "title_selectors": [
                "[data-testid='product-name']",
                ".product-title",
                ".product-name",
                "h1[class*='title']"
            ],
            "sku_selectors": [
                "[data-testid='product-detail']",
                ".product-details",
                ".style-id",
                "[class*='sku']"
            ],
            "image_selectors": [
                "[data-testid='product-media'] img",
                ".product-media img",
                ".hero-image img",
                "picture img"
            ]
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search StockX products with multiple fallback strategies"""
        products = []
        
        try:
            # Strategy 1: Try StockX API endpoints
            products = await self._try_stockx_api_search(keyword)
            if products:
                logger.info(f"StockX API search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.OFFICIAL_API] += 1
                return products
            
            # Strategy 2: Try StockX web search with JSON extraction
            products = await self._try_stockx_web_search(keyword)
            if products:
                logger.info(f"StockX web search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.SCRIPT_JSON] += 1
                return products
            
            # Strategy 3: Fallback to HTML parsing
            products = await self._try_stockx_html_search(keyword)
            if products:
                logger.info(f"StockX HTML search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.HTML_STRUCTURED] += 1
                return products
            
            logger.warning(f"All StockX search strategies failed for keyword: {keyword}")
            
        except Exception as e:
            logger.error(f"StockX search failed for '{keyword}': {e}")
        
        return products
    
    async def _try_stockx_api_search(self, keyword: str) -> List[SneakerProduct]:
        """Try StockX API endpoints"""
        for api_config in self.api_endpoints:
            try:
                search_params = {
                    "category": "sneakers",
                    "page": 1,
                    "_search": keyword,
                    "dataType": "product"
                }
                
                if api_config["name"] == "browse_api":
                    search_params.update({
                        "productCategory": "sneakers",
                        "sort": "featured",
                        "order": "DESC"
                    })
                elif api_config["name"] == "search_api":
                    search_params = {"query": keyword, "type": "product"}
                
                response = await self._make_robust_request(
                    api_config["url"],
                    params=search_params,
                    headers=api_config["headers"]
                )
                
                if response:
                    data = await response.json()
                    products = await self._parse_stockx_api_response(data)
                    if products:
                        return products
                        
            except Exception as e:
                logger.debug(f"StockX API {api_config['name']} failed: {e}")
                continue
        
        return []
    
    async def _try_stockx_web_search(self, keyword: str) -> List[SneakerProduct]:
        """Try StockX web search with enhanced JSON extraction"""
        try:
            search_url = f"{self.base_url}/search?s={quote_plus(keyword)}"
            
            response = await self._make_robust_request(search_url)
            if not response:
                return []
            
            html_content = await response.text()
            
            # Use enhanced parsing methods from base class
            result = await self._try_multiple_parsing_methods(html_content, search_url)
            
            if result.success and result.data:
                return await self._convert_to_stockx_products(result.data, result.method)
            
        except Exception as e:
            logger.error(f"StockX web search failed: {e}")
        
        return []
    
    async def _try_stockx_html_search(self, keyword: str) -> List[SneakerProduct]:
        """Fallback HTML search using StockX-specific patterns"""
        try:
            search_url = f"{self.base_url}/search?s={quote_plus(keyword)}"
            
            response = await self._make_robust_request(search_url)
            if not response:
                return []
            
            html_content = await response.text()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            products = []
            
            # Look for product cards using various selectors
            card_selectors = [
                "[data-testid='product-item']",
                ".product-item",
                "[class*='product-item']",
                ".browse-grid-item",
                "[class*='grid-item']"
            ]
            
            for selector in card_selectors:
                product_cards = soup.select(selector)
                if product_cards:
                    for card in product_cards:
                        product = await self._parse_stockx_product_card(card, search_url)
                        if product:
                            products.append(product)
                    
                    if products:
                        break
            
            return products[:10]
            
        except Exception as e:
            logger.error(f"StockX HTML search failed: {e}")
            return []
    
    async def _parse_stockx_api_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse StockX API response with multiple data structure support"""
        products = []
        
        try:
            # StockX API can have different response structures
            possible_paths = [
                ["Products"],
                ["products"],
                ["data", "browse", "results", "edges"],
                ["results"],
                ["edges"]
            ]
            
            products_data = None
            for path in possible_paths:
                current = data
                try:
                    for key in path:
                        current = current[key]
                    if isinstance(current, list):
                        products_data = current
                        break
                except (KeyError, TypeError):
                    continue
            
            if not products_data:
                return products
            
            for item in products_data[:10]:
                try:
                    # Handle GraphQL edge structure
                    if "node" in item:
                        item = item["node"]
                    
                    product = await self._create_stockx_product_from_api(item)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Failed to parse StockX API product: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Failed to parse StockX API response: {e}")
        
        return products
    
    async def _create_stockx_product_from_api(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from StockX API data"""
        try:
            # Extract basic info with multiple fallbacks
            name = (
                item.get("title") or 
                item.get("name") or 
                item.get("shortDescription") or 
                item.get("productName", "")
            )
            
            # Extract market data
            market = item.get("market", {})
            bid_ask_data = market.get("bidAskData", {}) if market else {}
            
            # Get current price (last sale or lowest ask)
            price = None
            if "lastSale" in market:
                price = market["lastSale"]
            elif "lowestAsk" in bid_ask_data:
                price = bid_ask_data["lowestAsk"]
            elif "highestBid" in bid_ask_data:
                price = bid_ask_data["highestBid"]
            elif "retailPrice" in item:
                price = item["retailPrice"]
            
            # Extract URL
            url = None
            if "urlKey" in item:
                url = f"{self.base_url}/{item['urlKey']}"
            elif "slug" in item:
                url = f"{self.base_url}/{item['slug']}"
            
            # Extract image
            image_url = None
            if "media" in item:
                media = item["media"]
                if "imageUrl" in media:
                    image_url = media["imageUrl"]
                elif "thumbUrl" in media:
                    image_url = media["thumbUrl"]
            elif "image" in item:
                image_url = item["image"]
            
            # Extract SKU/style code
            sku = item.get("styleId") or item.get("sku", "")
            
            # Extract brand info
            brand_info = item.get("brand", {})
            brand = brand_info.get("name", "") if isinstance(brand_info, dict) else str(brand_info)
            
            if not name or not price:
                return None
            
            # Parse model and colorway from name
            model, colorway = self._parse_stockx_product_name(name, brand)
            
            # Create resell data
            resell_data = None
            if market:
                resell_data = ResellData(
                    platform=self.retailer,
                    last_sale=market.get("lastSale"),
                    lowest_ask=bid_ask_data.get("lowestAsk"),
                    highest_bid=bid_ask_data.get("highestBid"),
                    sales_last_72h=market.get("salesLast72Hours", 0),
                    price_premium=self._calculate_price_premium(price, item.get("retailPrice")),
                    last_updated=datetime.now()
                )
            
            return SneakerProduct(
                name=name,
                brand=brand or self._extract_brand_from_name(name),
                model=model,
                colorway=colorway,
                sku=sku,
                price=float(price) if price else None,
                sizes=[],  # Sizes would need separate API call
                retailer=self.retailer,
                url=url or "",
                image=image_url,
                in_stock=True,  # StockX always has market data
                resell_data=resell_data,
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to create StockX product from API data: {e}")
            return None
    
    async def _parse_stockx_product_card(self, card, base_url: str) -> Optional[SneakerProduct]:
        """Parse individual StockX product card from HTML"""
        try:
            # Extract name
            name = None
            for selector in self.stockx_patterns["title_selectors"]:
                title_elem = card.select_one(selector)
                if title_elem:
                    name = title_elem.get_text(strip=True)
                    break
            
            if not name:
                return None
            
            # Extract price
            price = None
            for selector in self.stockx_patterns["price_selectors"]:
                price_elem = card.select_one(selector)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    price = self._extract_price(price_text)
                    if price:
                        break
            
            # Extract URL
            url = None
            link_elem = card.find("a")
            if link_elem and link_elem.get("href"):
                url = urljoin(base_url, link_elem["href"])
            
            # Extract image
            image_url = None
            for selector in self.stockx_patterns["image_selectors"]:
                img_elem = card.select_one(selector)
                if img_elem:
                    image_url = img_elem.get("src") or img_elem.get("data-src")
                    if image_url:
                        break
            
            if not name:
                return None
            
            # Extract brand and parse name
            brand = self._extract_brand_from_name(name)
            model, colorway = self._parse_stockx_product_name(name, brand)
            
            return SneakerProduct(
                name=name,
                brand=brand,
                model=model,
                colorway=colorway,
                sku="",
                price=price,
                sizes=[],
                retailer=self.retailer,
                url=url or "",
                image=image_url,
                in_stock=bool(price),
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse StockX product card: {e}")
            return None
    
    async def _convert_to_stockx_products(self, data: Dict, method: ScrapingMethod) -> List[SneakerProduct]:
        """Convert generic scraped data to StockX products"""
        products = []
        
        try:
            if method == ScrapingMethod.JSON_LD:
                if isinstance(data, dict) and data.get("@type") == "Product":
                    product = await self._create_product_from_json_ld(data)
                    if product:
                        products.append(product)
            
            elif method in [ScrapingMethod.SCRIPT_JSON, ScrapingMethod.HTML_STRUCTURED]:
                if isinstance(data, dict):
                    product = await self._create_product_from_structured_data(data)
                    if product:
                        products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to convert StockX data: {e}")
        
        return products
    
    def _parse_stockx_product_name(self, name: str, brand: str = "") -> tuple[str, str]:
        """Parse StockX product name into model and colorway"""
        if not name:
            return "", ""
        
        name = name.strip()
        
        # Remove brand from beginning if present
        if brand and name.lower().startswith(brand.lower()):
            name = name[len(brand):].strip()
        
        # StockX-specific parsing patterns
        patterns = [
            (r"(.+?)\s+['\"](.+?)['\"]", r"\1", r"\2"),  # Model "Colorway"
            (r"(.+?)\s+\((.+?)\)", r"\1", r"\2"),       # Model (Colorway)
            (r"(.+?)\s+-\s+(.+)", r"\1", r"\2"),        # Model - Colorway
            (r"(.+?)\s+(.+)", r"\1", r"\2"),            # Model Colorway (fallback)
        ]
        
        for pattern, model_group, colorway_group in patterns:
            match = re.match(pattern, name)
            if match:
                model = match.group(1).strip()
                colorway = match.group(2).strip()
                return model, colorway
        
        return name, ""
    
    def _extract_brand_from_name(self, name: str) -> str:
        """Extract brand from product name"""
        if not name:
            return ""
        
        name_lower = name.lower()
        
        # Common sneaker brands
        brands = [
            "nike", "adidas", "jordan", "air jordan", "yeezy", "converse", 
            "vans", "new balance", "puma", "reebok", "asics", "under armour",
            "balenciaga", "gucci", "off-white", "fear of god"
        ]
        
        for brand in sorted(brands, key=len, reverse=True):  # Check longer brands first
            if brand in name_lower:
                return brand.title()
        
        return ""
    
    def _calculate_price_premium(self, current_price: float, retail_price: float) -> Optional[float]:
        """Calculate price premium over retail"""
        if not current_price or not retail_price or retail_price <= 0:
            return None
        
        return ((current_price - retail_price) / retail_price) * 100
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed StockX product information with enhanced parsing"""
        try:
            response = await self._make_robust_request(product_url)
            if not response:
                return None
            
            html_content = await response.text()
            
            # Use enhanced parsing methods
            result = await self._try_multiple_parsing_methods(html_content, product_url)
            
            if result.success and result.data:
                products = await self._convert_to_stockx_products(result.data, result.method)
                return products[0] if products else None
            
            logger.warning(f"Failed to extract StockX product details from {product_url}")
            
        except Exception as e:
            logger.error(f"Failed to get StockX product details for {product_url}: {e}")
        
        return None
    
    async def get_resell_data(self, keyword: str) -> List[ResellData]:
        """Get resell market data for keyword"""
        try:
            products = await self.search_products(keyword)
            resell_data = []
            
            for product in products:
                if product.resell_data:
                    resell_data.append(product.resell_data)
            
            return resell_data
            
        except Exception as e:
            logger.error(f"Failed to get StockX resell data for '{keyword}': {e}")
            return []
