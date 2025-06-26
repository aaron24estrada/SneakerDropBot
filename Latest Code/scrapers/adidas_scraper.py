"""
Adidas sneaker scraper
"""
import json
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, quote_plus
from loguru import logger

from database.models import SneakerProduct, SneakerSize, Retailer
from scrapers.base_scraper import BaseScraper


class AdidasScraper(BaseScraper):
    """Adidas sneaker scraper"""
    
    def __init__(self):
        super().__init__(Retailer.ADIDAS)
        self.base_url = "https://www.adidas.com"
        self.search_url = "https://www.adidas.com/us/search"
    
    async def search_products(self, keyword: str) -> List[SneakerProduct]:
        """Search Adidas products by keyword"""
        products = []
        
        try:
            # Build search URL
            search_url = f"{self.search_url}?q={quote_plus(keyword)}"
            
            response = await self._make_request(search_url)
            if not response:
                logger.warning(f"Failed to get Adidas search results for: {keyword}")
                return products
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract product data from script tags or HTML
            products = await self._parse_search_page(soup)
            
            logger.info(f"Adidas search for '{keyword}' found {len(products)} products")
            
        except Exception as e:
            logger.error(f"Adidas search failed for '{keyword}': {e}")
        
        return products
    
    async def get_product_details(self, product_url: str) -> Optional[SneakerProduct]:
        """Get detailed Adidas product information"""
        try:
            response = await self._make_request(product_url)
            if not response:
                return None
            
            html = await response.text()
            soup = await self._parse_html(html)
            
            # Extract product data
            product_data = await self._extract_product_data(soup)
            
            if product_data:
                return await self._create_product_from_data(product_data, product_url)
            
        except Exception as e:
            logger.error(f"Failed to get Adidas product details for {product_url}: {e}")
        
        return None
    
    async def _parse_search_page(self, soup) -> List[SneakerProduct]:
        """Parse Adidas search results page"""
        products = []
        
        # Look for product cards
        product_cards = soup.find_all("div", class_=re.compile(r"grid-item"))
        
        for card in product_cards:
            try:
                # Extract product link
                link_elem = card.find("a", href=True)
                if not link_elem:
                    continue
                
                product_url = urljoin(self.base_url, link_elem["href"])
                
                # Extract product name
                name_elem = card.find("h3") or card.find("div", class_=re.compile(r"product-card-title"))
                if not name_elem:
                    continue
                
                name = name_elem.get_text(strip=True)
                
                # Extract price
                price_elem = card.find("div", class_=re.compile(r"price"))
                price = None
                if price_elem:
                    price = self._extract_price(price_elem.get_text(strip=True))
                
                # Extract image
                img_elem = card.find("img")
                image_url = img_elem.get("src", "") if img_elem else ""
                
                # Parse product name
                brand, model, colorway = self._parse_product_name(name)
                
                product = SneakerProduct(
                    name=self._normalize_product_name(name),
                    brand=brand,
                    model=model,
                    colorway=colorway,
                    sku="",  # Will be filled in product details
                    retailer=self.retailer,
                    url=product_url,
                    image_url=image_url,
                    price=price,
                    is_in_stock=True  # Assume in stock from search
                )
                
                products.append(product)
            
            except Exception as e:
                logger.warning(f"Failed to parse Adidas product card: {e}")
                continue
        
        return products
    
    async def _extract_product_data(self, soup) -> Optional[Dict]:
        """Extract product data from Adidas product page"""
        try:
            # Look for JSON-LD structured data
            json_ld = soup.find("script", type="application/ld+json")
            if json_ld:
                try:
                    data = json.loads(json_ld.string)
                    if data.get("@type") == "Product":
                        return data
                except json.JSONDecodeError:
                    pass
            
            # Look for product data in script tags
            script_tags = soup.find_all("script")
            for script in script_tags:
                if script.string and "window.INITIAL_STATE" in script.string:
                    try:
                        # Extract the JSON data
                        start = script.string.find("window.INITIAL_STATE = ") + 24
                        end = script.string.find(";\n", start)
                        
                        if start > 23 and end > start:
                            json_str = script.string[start:end]
                            data = json.loads(json_str)
                            
                            # Navigate to product data
                            if "product" in data:
                                return data["product"]
                            
                    except (json.JSONDecodeError, KeyError):
                        continue
            
            # Fallback to HTML parsing
            return await self._parse_product_html(soup)
            
        except Exception as e:
            logger.error(f"Failed to extract Adidas product data: {e}")
            return None
    
    async def _parse_product_html(self, soup) -> Optional[Dict]:
        """Parse product data from HTML elements"""
        try:
            # Extract product name
            name_elem = soup.find("h1", class_=re.compile(r"product-title"))
            if not name_elem:
                name_elem = soup.find("h1")
            
            if not name_elem:
                return None
            
            name = name_elem.get_text(strip=True)
            
            # Extract price
            price_elem = soup.find("div", class_=re.compile(r"price-value"))
            price_text = price_elem.get_text(strip=True) if price_elem else ""
            
            # Extract SKU/model number
            sku_elem = soup.find("span", class_=re.compile(r"product-code"))
            sku = sku_elem.get_text(strip=True) if sku_elem else ""
            
            # Clean up SKU
            if sku:
                sku = sku.replace("Product code: ", "").strip()
            
            # Extract availability
            availability_elem = soup.find("div", class_=re.compile(r"availability"))
            is_available = True
            if availability_elem:
                availability_text = availability_elem.get_text(strip=True).lower()
                is_available = "in stock" in availability_text or "available" in availability_text
            
            # Extract image
            img_elem = soup.find("img", class_=re.compile(r"product-image"))
            image_url = img_elem.get("src", "") if img_elem else ""
            
            return {
                "name": name,
                "price": price_text,
                "sku": sku,
                "is_available": is_available,
                "image": image_url
            }
            
        except Exception as e:
            logger.error(f"Failed to parse Adidas product HTML: {e}")
            return None
    
    async def _create_product_from_data(self, data: Dict, product_url: str) -> SneakerProduct:
        """Create SneakerProduct from extracted data"""
        name = data.get("name", "")
        
        # Parse brand, model, colorway
        brand, model, colorway = self._parse_product_name(name)
        
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
        image_url = data.get("image", "")
        if isinstance(image_url, list) and image_url:
            image_url = image_url[0]
        
        # Extract availability
        is_in_stock = data.get("is_available", True)
        if "offers" in data:
            availability = data["offers"].get("availability", "").lower()
            is_in_stock = "instock" in availability
        
        return SneakerProduct(
            name=self._normalize_product_name(name),
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
    
    def _parse_product_name(self, name: str) -> tuple[str, str, str]:
        """Parse product name into brand, model, and colorway"""
        if not name:
            return "Adidas", "", ""
        
        # Common Adidas patterns
        name_lower = name.lower()
        
        # Determine brand
        brand = "Adidas"
        if "yeezy" in name_lower:
            brand = "Yeezy"
        
        # Extract model and colorway
        parts = name.split()
        
        if len(parts) >= 2:
            if "yeezy" in name_lower:
                # Yeezy pattern: "Yeezy Boost 350 V2 Cream"
                if "boost" in name_lower:
                    model_parts = []
                    colorway_parts = []
                    found_colorway = False
                    
                    for part in parts:
                        if part.lower() in ["yeezy", "boost", "350", "500", "700", "v2", "v3"]:
                            if not found_colorway:
                                model_parts.append(part)
                        else:
                            found_colorway = True
                            colorway_parts.append(part)
                    
                    model = " ".join(model_parts) if model_parts else "Yeezy"
                    colorway = " ".join(colorway_parts)
                else:
                    # Simple yeezy pattern
                    model = " ".join(parts[:3]) if len(parts) >= 3 else " ".join(parts[:2])
                    colorway = " ".join(parts[3:]) if len(parts) > 3 else ""
            else:
                # Regular Adidas pattern: "Ultraboost 22 Triple White"
                if len(parts) >= 3:
                    model = " ".join(parts[:2])
                    colorway = " ".join(parts[2:])
                else:
                    model = " ".join(parts[:2]) if len(parts) >= 2 else parts[0]
                    colorway = ""
        else:
            model = name
            colorway = ""
        
        return brand, model, colorway
