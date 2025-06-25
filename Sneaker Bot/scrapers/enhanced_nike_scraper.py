"""
Enhanced Nike scraper with multiple fallback strategies and robust error handling
"""
import json
import re
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, quote_plus
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.enhanced_base_scraper import EnhancedBaseScraper, ScrapingMethod, ScrapingResult


class EnhancedNikeScraper(EnhancedBaseScraper):
    """Enhanced Nike scraper with multiple API endpoints and fallback strategies"""
    
    def __init__(self):
        super().__init__(Retailer.NIKE)
        self.base_url = "https://www.nike.com"
        
        # Multiple API endpoints (Nike has several)
        self.api_endpoints = [
            {
                "name": "nike_api_v1",
                "base": "https://api.nike.com/cic/browse/v2",
                "search": "https://api.nike.com/cic/browse/v2",
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": "Nike/4.0 CFNetwork/1220.1 Darwin/20.0.0"
                }
            },
            {
                "name": "nike_web_api",
                "base": "https://www.nike.com/api",
                "search": "https://www.nike.com/api/users/search",
                "headers": {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest"
                }
            }
        ]
        
        # Common Nike product patterns for fallback parsing
        self.nike_patterns = {
            "price_selectors": [
                "[data-test='product-price']",
                ".product-price",
                ".price-value",
                "[class*='price-current']",
                ".current-price"
            ],
            "title_selectors": [
                "[data-test='product-title']",
                "#pdp_product_title",
                ".product-title",
                "h1[class*='headline']"
            ],
            "sku_selectors": [
                "[data-test='product-sub-title']",
                ".product-code",
                ".style-color",
                "[class*='style-color']"
            ],
            "image_selectors": [
                "[data-test='product-image'] img",
                ".product-image img",
                "[class*='hero-image'] img",
                "picture img"
            ]
        }
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search Nike products with multiple fallback strategies"""
        products = []
        
        try:
            # Strategy 1: Try official Nike API
            products = await self._try_nike_api_search(keyword)
            if products:
                logger.info(f"Nike API search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.OFFICIAL_API] += 1
                return products
            
            # Strategy 2: Try Nike web search with JSON extraction
            products = await self._try_nike_web_search(keyword)
            if products:
                logger.info(f"Nike web search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.SCRIPT_JSON] += 1
                return products
            
            # Strategy 3: Fallback to HTML parsing
            products = await self._try_nike_html_search(keyword)
            if products:
                logger.info(f"Nike HTML search successful for '{keyword}': {len(products)} products")
                self.health_stats["method_success"][ScrapingMethod.HTML_STRUCTURED] += 1
                return products
            
            logger.warning(f"All Nike search strategies failed for keyword: {keyword}")
            
        except Exception as e:
            logger.error(f"Nike search failed for '{keyword}': {e}")
        
        return products
    
    async def _try_nike_api_search(self, keyword: str) -> List[SneakerProduct]:
        """Try Nike's official API endpoints"""
        for api_config in self.api_endpoints:
            try:
                search_params = {
                    "queryid": "products",
                    "anonymousId": "anonymous",
                    "country": "US",
                    "endpoint": "/product_feed/rollup_threads/v2",
                    "language": "en",
                    "localizedRangeStr": "{lowestPrice}–{highestPrice}",
                    "currency": "USD",
                    "offset": "0",
                    "limit": "24",
                    "filter": f"marketplace(US)&language(en)&productType(Footwear)&searchTerms({keyword})"
                }
                
                response = await self._make_robust_request(
                    api_config["search"],
                    params=search_params,
                    headers=api_config["headers"]
                )
                
                if response:
                    data = await response.json()
                    products = await self._parse_nike_api_response(data)
                    if products:
                        return products
                        
            except Exception as e:
                logger.debug(f"Nike API {api_config['name']} failed: {e}")
                continue
        
        return []
    
    async def _try_nike_web_search(self, keyword: str) -> List[SneakerProduct]:
        """Try Nike web search with enhanced JSON extraction"""
        try:
            search_url = f"{self.base_url}/w/shoes-y7ok?q={quote_plus(keyword)}"
            
            response = await self._make_robust_request(search_url)
            if not response:
                return []
            
            html_content = await response.text()
            
            # Use the enhanced parsing methods from base class
            result = await self._try_multiple_parsing_methods(html_content, search_url)
            
            if result.success and result.data:
                # Convert the generic data to Nike-specific products
                return await self._convert_to_nike_products(result.data, result.method)
            
        except Exception as e:
            logger.error(f"Nike web search failed: {e}")
        
        return []
    
    async def _try_nike_html_search(self, keyword: str) -> List[SneakerProduct]:
        """Fallback HTML search using Nike-specific patterns"""
        try:
            search_url = f"{self.base_url}/w/shoes-y7ok?q={quote_plus(keyword)}"
            
            response = await self._make_robust_request(search_url)
            if not response:
                return []
            
            html_content = await response.text()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            products = []
            
            # Look for product cards using various selectors
            card_selectors = [
                "[data-test='product-card']",
                ".product-card",
                "[class*='product-card']",
                ".grid-item",
                "[class*='grid-item']"
            ]
            
            for selector in card_selectors:
                product_cards = soup.select(selector)
                if product_cards:
                    for card in product_cards:
                        product = await self._parse_nike_product_card(card, search_url)
                        if product:
                            products.append(product)
                    
                    if products:
                        break  # Found products with this selector
            
            return products[:10]  # Limit to 10 products
            
        except Exception as e:
            logger.error(f"Nike HTML search failed: {e}")
            return []
    
    async def _parse_nike_api_response(self, data: Dict) -> List[SneakerProduct]:
        """Parse Nike API response with multiple data structure support"""
        products = []
        
        try:
            # Nike API can have different response structures
            possible_paths = [
                ["data", "products", "products"],
                ["products"],
                ["objects"],
                ["data", "products"]
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
            
            for item in products_data[:10]:  # Limit to 10 products
                try:
                    product = await self._create_nike_product_from_api(item)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Failed to parse Nike API product: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Failed to parse Nike API response: {e}")
        
        return products
    
    async def _create_nike_product_from_api(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from Nike API data"""
        try:
            # Extract basic info with multiple fallbacks
            name = (
                item.get("title") or 
                item.get("displayName") or 
                item.get("name") or 
                item.get("productDisplayName", "")
            )
            
            # Extract price
            price = None
            price_data = item.get("price") or item.get("currentPrice") or item.get("retailPrice")
            if price_data:
                if isinstance(price_data, dict):
                    price = price_data.get("currentPrice") or price_data.get("msrp") or price_data.get("value")
                else:
                    price = price_data
            
            # Extract URL
            url = None
            if "productId" in item:
                url = f"{self.base_url}/t/{item['productId']}"
            elif "uri" in item:
                url = urljoin(self.base_url, item["uri"])
            elif "url" in item:
                url = item["url"]
            
            # Extract image
            image_url = None
            if "imageUrl" in item:
                image_url = item["imageUrl"]
            elif "images" in item and item["images"]:
                if isinstance(item["images"], list):
                    image_url = item["images"][0].get("src") or item["images"][0].get("url")
                elif isinstance(item["images"], dict):
                    image_url = item["images"].get("portraitURL") or item["images"].get("squarishURL")
            
            # Extract SKU
            sku = item.get("styleColor") or item.get("sku") or item.get("gtin", "")
            
            if not name or not price:
                return None
            
            # Parse brand, model, colorway
            brand, model, colorway = self._parse_product_name(name)
            
            return SneakerProduct(
                name=name,
                brand=brand or "Nike",
                model=model,
                colorway=colorway,
                sku=sku,
                price=float(price) if price else None,
                sizes=[],  # Sizes would need separate API call
                retailer=self.retailer,
                url=url or "",
                image=image_url,
                in_stock=True,  # Assume in stock if in search results
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to create Nike product from API data: {e}")
            return None
    
    async def _parse_nike_product_card(self, card, base_url: str) -> Optional[SneakerProduct]:
        """Parse individual Nike product card from HTML"""
        try:
            # Extract name using Nike-specific patterns
            name = None
            for selector in self.nike_patterns["title_selectors"]:
                title_elem = card.select_one(selector)
                if title_elem:
                    name = title_elem.get_text(strip=True)
                    break
            
            if not name:
                return None
            
            # Extract price
            price = None
            for selector in self.nike_patterns["price_selectors"]:
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
            for selector in self.nike_patterns["image_selectors"]:
                img_elem = card.select_one(selector)
                if img_elem:
                    image_url = img_elem.get("src") or img_elem.get("data-src")
                    if image_url:
                        break
            
            # Extract SKU/style code
            sku = ""
            for selector in self.nike_patterns["sku_selectors"]:
                sku_elem = card.select_one(selector)
                if sku_elem:
                    sku = sku_elem.get_text(strip=True)
                    break
            
            if not name:
                return None
            
            # Parse brand, model, colorway
            brand, model, colorway = self._parse_product_name(name)
            
            return SneakerProduct(
                name=name,
                brand=brand or "Nike",
                model=model,
                colorway=colorway,
                sku=sku,
                price=price,
                sizes=[],
                retailer=self.retailer,
                url=url or "",
                image=image_url,
                in_stock=bool(price),  # Assume in stock if price is available
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse Nike product card: {e}")
            return None
    
    async def _convert_to_nike_products(self, data: Dict, method: ScrapingMethod) -> List[SneakerProduct]:
        """Convert generic scraped data to Nike products"""
        products = []
        
        try:
            if method == ScrapingMethod.JSON_LD:
                # Handle JSON-LD data
                if isinstance(data, dict) and data.get("@type") == "Product":
                    product = await self._create_product_from_json_ld(data)
                    if product:
                        products.append(product)
            
            elif method in [ScrapingMethod.SCRIPT_JSON, ScrapingMethod.HTML_STRUCTURED]:
                # Handle structured data
                if isinstance(data, dict):
                    product = await self._create_product_from_structured_data(data)
                    if product:
                        products.append(product)
        
        except Exception as e:
            logger.error(f"Failed to convert Nike data: {e}")
        
        return products
    
    async def _create_product_from_json_ld(self, data: Dict) -> Optional[SneakerProduct]:
        """Create product from JSON-LD data"""
        try:
            name = data.get("name", "")
            
            # Extract price from offers
            price = None
            offers = data.get("offers")
            if offers:
                if isinstance(offers, list) and offers:
                    price_str = offers[0].get("price")
                elif isinstance(offers, dict):
                    price_str = offers.get("price")
                
                if price_str:
                    price = self._extract_price(str(price_str))
            
            # Extract image
            image_url = None
            image_data = data.get("image")
            if image_data:
                if isinstance(image_data, list) and image_data:
                    image_url = image_data[0]
                elif isinstance(image_data, str):
                    image_url = image_data
            
            # Extract SKU
            sku = data.get("sku", "") or data.get("gtin", "")
            
            if not name:
                return None
            
            brand, model, colorway = self._parse_product_name(name)
            
            return SneakerProduct(
                name=name,
                brand=brand or "Nike",
                model=model,
                colorway=colorway,
                sku=sku,
                price=price,
                sizes=[],
                retailer=self.retailer,
                url=data.get("url", ""),
                image=image_url,
                in_stock=bool(price),
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to create product from JSON-LD: {e}")
            return None
    
    async def _create_product_from_structured_data(self, data: Dict) -> Optional[SneakerProduct]:
        """Create product from structured HTML data"""
        try:
            name = data.get("title") or data.get("name", "")
            price = self._extract_price(str(data.get("price", ""))) if data.get("price") else None
            image_url = data.get("image")
            sku = data.get("sku", "")
            url = data.get("url", "")
            
            if not name:
                return None
            
            brand, model, colorway = self._parse_product_name(name)
            
            return SneakerProduct(
                name=name,
                brand=brand or "Nike",
                model=model,
                colorway=colorway,
                sku=sku,
                price=price,
                sizes=[],
                retailer=self.retailer,
                url=url,
                image=image_url,
                in_stock=bool(price),
                last_updated=datetime.now()
            )
            
        except Exception as e:
            logger.debug(f"Failed to create product from structured data: {e}")
            return None
    
    def _parse_product_name(self, name: str) -> tuple[str, str, str]:
        """Parse Nike product name into brand, model, and colorway"""
        if not name:
            return "Nike", "", ""
        
        name = name.strip()
        
        # Nike-specific parsing patterns
        patterns = [
            (r"Nike\s+(.+?)\s+(['\"].*['\"])", "Nike", r"\1", r"\2"),  # Nike Model "Colorway"
            (r"Air Jordan\s+(\d+\w*)\s+(.+)", "Jordan", r"\1", r"\2"),  # Air Jordan 4 Bred
            (r"Jordan\s+(\d+\w*)\s+(.+)", "Jordan", r"\1", r"\2"),     # Jordan 4 Bred
            (r"Air Max\s+(\w+)\s+(.+)", "Nike", r"Air Max \1", r"\2"),  # Air Max 90 Infrared
            (r"Dunk\s+(\w+)\s+(.+)", "Nike", r"Dunk \1", r"\2"),       # Dunk Low Panda
        ]
        
        for pattern, brand, model_group, colorway_group in patterns:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                model = re.sub(r'\\(\d+)', lambda m: match.group(int(m.group(1))), model_group)
                colorway = re.sub(r'\\(\d+)', lambda m: match.group(int(m.group(1))), colorway_group)
                return brand, model, colorway.strip('"\'')
        
        # Fallback: split on common delimiters
        parts = re.split(r'\s+["\'-]\s+|\s+\|\s+|\s+–\s+', name, 1)
        if len(parts) == 2:
            return "Nike", parts[0], parts[1]
        
        return "Nike", name, ""
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed Nike product information with enhanced parsing"""
        try:
            response = await self._make_robust_request(product_url)
            if not response:
                return None
            
            html_content = await response.text()
            
            # Use enhanced parsing methods
            result = await self._try_multiple_parsing_methods(html_content, product_url)
            
            if result.success and result.data:
                products = await self._convert_to_nike_products(result.data, result.method)
                return products[0] if products else None
            
            logger.warning(f"Failed to extract Nike product details from {product_url}")
            
        except Exception as e:
            logger.error(f"Failed to get Nike product details for {product_url}: {e}")
        
        return None
