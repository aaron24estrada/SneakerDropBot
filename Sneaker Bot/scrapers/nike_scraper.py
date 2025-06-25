"""
Nike sneaker scraper
"""
import json
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, quote_plus
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.base_scraper import BaseScraper


class NikeScraper(BaseScraper):
    """Nike sneaker scraper"""
    
    def __init__(self):
        super().__init__(Retailer.NIKE)
        self.base_url = "https://www.nike.com"
        self.search_url = "https://www.nike.com/w/shoes-y7ok"
        self.api_url = "https://api.nike.com/cic/browse/v2"
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search Nike products by keyword"""
        products = []
        
        try:
            # Use Nike's search API
            search_params = {
                "queryid": "products",
                "anonymousId": "anonymous",
                "country": "US",
                "endpoint": "/product_feed/rollup_threads/v2",
                "language": "en",
                "localizedRangeStr": "{lowestPrice}–{highestPrice}",
                "currency": "USD",
                "offset": "0",
                "limit": "24"
            }
            
            # Add search query
            search_url = f"{self.base_url}/w/shoes-y7ok?q={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                logger.warning(f"Failed to get Nike search results for: {keyword}")
                return products
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract product data from script tags
            script_tags = soup.find_all("script", type="application/json")
            
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    if "products" in data:
                        products.extend(await self._parse_search_results(data["products"]))
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
            
            # Fallback: parse product cards from HTML
            if not products:
                products = await self._parse_product_cards(soup)
            
            logger.info(f"Nike search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"Nike search failed for '{keyword}': {e}")
        
        return products
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed Nike product information"""
        try:
            response = await self._make_request(product_url)
            if not response:
                return None
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract product data from JSON-LD or script tags
            product_data = await self._extract_product_json(soup)
            
            if not product_data:
                # Fallback to HTML parsing
                product_data = await self._parse_product_html(soup, product_url)
            
            if product_data:
                return await self._create_product_from_data(product_data, product_url)
            
        except Exception as e:
            logger.error(f"Failed to get Nike product details for {product_url}: {e}")
        
        return None
    
    async def _parse_search_results(self, products_data: List[Dict]) -> List[SneakerProduct]:
        """Parse Nike search results from API response"""
        products = []
        
        for item in products_data:
            try:
                product = await self._create_product_from_search_item(item)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Failed to parse Nike search item: {e}")
                continue
        
        return products
    
    async def _parse_product_cards(self, soup) -> List[SneakerProduct]:
        """Parse product cards from Nike search page HTML"""
        products = []
        
        # Look for product cards
        product_cards = soup.find_all("div", class_=re.compile(r"product-card"))
        
        for card in product_cards:
            try:
                # Extract basic info from card
                name_elem = card.find("div", class_=re.compile(r"product-card__title"))
                link_elem = card.find("a", class_=re.compile(r"product-card__link"))
                price_elem = card.find("div", class_=re.compile(r"product-price"))
                
                if name_elem and link_elem:
                    name = name_elem.get_text(strip=True)
                    url = urljoin(self.base_url, link_elem.get("href", ""))
                    price = self._extract_price(price_elem.get_text(strip=True) if price_elem else "")
                    
                    # Extract basic product info
                    brand, model, colorway = self._parse_product_name(name)
                    
                    product = SneakerProduct(
                        name=self._normalize_product_name(name),
                        brand=brand,
                        model=model,
                        colorway=colorway,
                        sku="",  # Will be filled in product details
                        retailer=self.retailer,
                        url=url,
                        price=price,
                        is_in_stock=True  # Assume in stock from search
                    )
                    
                    products.append(product)
            
            except Exception as e:
                logger.warning(f"Failed to parse Nike product card: {e}")
                continue
        
        return products
    
    async def _extract_product_json(self, soup) -> Optional[Dict]:
        """Extract product data from JSON-LD or script tags"""
        # Look for JSON-LD structured data
        json_ld = soup.find("script", type="application/ld+json")
        if json_ld:
            try:
                data = json.loads(json_ld.string)
                if data.get("@type") == "Product":
                    return data
            except json.JSONDecodeError:
                pass
        
        # Look for Nike's product data in script tags
        script_tags = soup.find_all("script")
        for script in script_tags:
            if script.string and "window.INITIAL_REDUX_STATE" in script.string:
                try:
                    # Extract the JSON data
                    start = script.string.find("window.INITIAL_REDUX_STATE = ") + 30
                    end = script.string.find(";\n", start)
                    
                    if start > 29 and end > start:
                        json_str = script.string[start:end]
                        data = json.loads(json_str)
                        
                        # Navigate to product data
                        if "product" in data:
                            return data["product"]
                        
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return None
    
    async def _parse_product_html(self, soup, product_url: str) -> Optional[Dict]:
        """Parse product data from HTML elements"""
        try:
            # Extract basic product info
            title_elem = soup.find("h1", id="pdp_product_title")
            subtitle_elem = soup.find("h2", class_=re.compile(r"headline-5"))
            price_elem = soup.find("div", class_=re.compile(r"product-price"))
            
            # Extract SKU/style code
            sku_elem = soup.find("span", class_=re.compile(r"style-color"))
            
            if not title_elem:
                return None
            
            name = title_elem.get_text(strip=True)
            subtitle = subtitle_elem.get_text(strip=True) if subtitle_elem else ""
            price_text = price_elem.get_text(strip=True) if price_elem else ""
            sku = sku_elem.get_text(strip=True) if sku_elem else ""
            
            # Clean up SKU
            if sku:
                sku = sku.replace("Style: ", "").replace("Color: ", "").strip()
            
            return {
                "name": name,
                "subtitle": subtitle,
                "price": price_text,
                "sku": sku,
                "url": product_url
            }
            
        except Exception as e:
            logger.error(f"Failed to parse Nike product HTML: {e}")
            return None
    
    async def _create_product_from_data(self, data: Dict, product_url: str) -> SneakerProduct:
        """Create SneakerProduct from extracted data"""
        name = data.get("name", "")
        subtitle = data.get("subtitle", "")
        full_name = f"{name} {subtitle}".strip()
        
        # Parse brand, model, colorway
        brand, model, colorway = self._parse_product_name(full_name)
        
        # Extract price
        price = None
        if "price" in data:
            price = self._extract_price(str(data["price"]))
        elif "offers" in data and "price" in data["offers"]:
            price = self._extract_price(str(data["offers"]["price"]))
        
        # Extract SKU
        sku = data.get("sku", "")
        if not sku and "gtin" in data:
            sku = data["gtin"]
        
        # Extract image
        image_url = None
        if "image" in data:
            if isinstance(data["image"], list) and data["image"]:
                image_url = data["image"][0]
            elif isinstance(data["image"], str):
                image_url = data["image"]
        
        # Extract availability
        is_in_stock = True
        if "offers" in data:
            availability = data["offers"].get("availability", "").lower()
            is_in_stock = "instock" in availability
        
        return SneakerProduct(
            name=self._normalize_product_name(full_name),
            brand=brand,
            model=model,
            colorway=colorway,
            sku=sku,
            retailer=self.retailer,
            url=product_url,
            image_url=image_url,
            price=price,
            is_in_stock=is_in_stock
        )
    
    async def _create_product_from_search_item(self, item: Dict) -> Optional[SneakerProduct]:
        """Create SneakerProduct from search API item"""
        try:
            name = item.get("title", "")
            subtitle = item.get("subtitle", "")
            full_name = f"{name} {subtitle}".strip()
            
            # Parse brand, model, colorway
            brand, model, colorway = self._parse_product_name(full_name)
            
            # Extract price
            price = None
            if "price" in item:
                price = self._extract_price(str(item["price"]["currentPrice"]))
            
            # Extract URL
            url = ""
            if "url" in item:
                url = urljoin(self.base_url, item["url"])
            
            # Extract image
            image_url = None
            if "images" in item and item["images"]:
                image_url = item["images"][0].get("src", "")
            
            return SneakerProduct(
                name=self._normalize_product_name(full_name),
                brand=brand,
                model=model,
                colorway=colorway,
                sku=item.get("gtin", ""),
                retailer=self.retailer,
                url=url,
                image_url=image_url,
                price=price,
                is_in_stock=True  # Assume in stock from search
            )
            
        except Exception as e:
            logger.warning(f"Failed to create Nike product from search item: {e}")
            return None
    
    def _parse_product_name(self, name: str) -> tuple[str, str, str]:
        """Parse product name into brand, model, and colorway"""
        if not name:
            return "Nike", "", ""
        
        # Common Nike patterns
        name_lower = name.lower()
        
        # Determine brand
        brand = "Nike"
        if "jordan" in name_lower:
            brand = "Jordan"
        elif "air force" in name_lower:
            brand = "Nike"
        
        # Extract model and colorway
        # This is a simplified approach - in production, you'd want more sophisticated parsing
        parts = name.split()
        
        if len(parts) >= 2:
            if "jordan" in name_lower:
                # Jordan pattern: "Air Jordan 1 Low Bred"
                if len(parts) >= 3:
                    model = " ".join(parts[:3])  # "Air Jordan 1" or "Jordan 1 Low"
                    colorway = " ".join(parts[3:]) if len(parts) > 3 else ""
                else:
                    model = " ".join(parts[:2])
                    colorway = ""
            else:
                # Nike pattern: "Air Max 90 Infrared"
                if len(parts) >= 3:
                    model = " ".join(parts[:3])
                    colorway = " ".join(parts[3:]) if len(parts) > 3 else ""
                else:
                    model = " ".join(parts[:2])
                    colorway = ""
        else:
            model = name
            colorway = ""
        
        return brand, model, colorway
