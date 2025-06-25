"""
Affiliate link management for SneakerDropBot
"""
import os
from typing import Dict, Optional, List
from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime
import asyncio

from loguru import logger
from database.models import Retailer, AffiliateClick, AffiliateEarning
from database.connection import db_manager


class AffiliateManager:
    """Manage affiliate links and revenue tracking"""
    
    def __init__(self):
        self.affiliate_codes = {
            # Retail partners
            Retailer.NIKE: {
                "code": os.getenv("NIKE_AFFILIATE_CODE", "sneakerdropbot"),
                "param": "affiliate_id",
                "commission_rate": 0.03,  # 3%
                "tracking_param": "utm_source"
            },
            Retailer.ADIDAS: {
                "code": os.getenv("ADIDAS_AFFILIATE_CODE", "sneakerdropbot"),
                "param": "partner_id", 
                "commission_rate": 0.025,  # 2.5%
                "tracking_param": "utm_campaign"
            },
            Retailer.FOOTLOCKER: {
                "code": os.getenv("FOOTLOCKER_AFFILIATE_CODE", "SDB123"),
                "param": "cm_mmc",
                "commission_rate": 0.04,  # 4%
                "tracking_param": "ref"
            },
            Retailer.FINISH_LINE: {
                "code": os.getenv("FINISHLINE_AFFILIATE_CODE", "SDBOT"),
                "param": "affiliate",
                "commission_rate": 0.035,  # 3.5%
                "tracking_param": "source"
            },
            
            # Resell platforms
            Retailer.STOCKX: {
                "code": os.getenv("STOCKX_AFFILIATE_CODE", "sneakerdropbot"),
                "param": "ref",
                "commission_rate": 0.02,  # 2%
                "tracking_param": "utm_source"
            },
            Retailer.GOAT: {
                "code": os.getenv("GOAT_AFFILIATE_CODE", "sneakerdropbot"),
                "param": "referrer",
                "commission_rate": 0.025,  # 2.5%
                "tracking_param": "utm_medium"
            },
            Retailer.STADIUM_GOODS: {
                "code": os.getenv("STADIUM_GOODS_AFFILIATE_CODE", "sneakerdropbot"),
                "param": "affiliate_id",
                "commission_rate": 0.03,  # 3%
                "tracking_param": "ref"
            }
        }
        
        # Alternative affiliate networks
        self.rakuten_partners = {
            "ebay": {
                "code": os.getenv("EBAY_RAKUTEN_CODE", "123456"),
                "base_url": "https://click.linksynergy.com/deeplink",
                "commission_rate": 0.015
            },
            "eastbay": {
                "code": os.getenv("EASTBAY_RAKUTEN_CODE", "789012"),
                "base_url": "https://click.linksynergy.com/deeplink",
                "commission_rate": 0.035
            }
        }
        
        # Click tracking
        self.click_tracking = {}
        
    def get_affiliate_link(self, original_url: str, retailer: Retailer, user_id: Optional[int] = None) -> str:
        """Generate affiliate link for a product URL"""
        try:
            affiliate_info = self.affiliate_codes.get(retailer)
            
            if not affiliate_info:
                # Return original URL if no affiliate program
                return original_url
            
            # Parse the original URL
            parsed_url = urlparse(original_url)
            query_params = parse_qs(parsed_url.query)
            
            # Add affiliate parameters
            affiliate_param = affiliate_info["param"]
            affiliate_code = affiliate_info["code"]
            tracking_param = affiliate_info["tracking_param"]
            
            # Set affiliate code
            query_params[affiliate_param] = [affiliate_code]
            
            # Add tracking parameters
            query_params[tracking_param] = ["sneakerdropbot"]
            query_params["utm_campaign"] = ["telegram_bot"]
            query_params["utm_medium"] = ["bot_alert"]
            
            if user_id:
                query_params["user_ref"] = [str(user_id)]
            
            # Build new URL
            new_query = urlencode(query_params, doseq=True)
            affiliate_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query}"
            
            # Track click (async)
            if user_id:
                asyncio.create_task(self._track_click(user_id, retailer, original_url, affiliate_url))
            
            return affiliate_url
            
        except Exception as e:
            logger.error(f"Error generating affiliate link for {retailer.value}: {e}")
            return original_url
    
    def get_resell_platform_link(self, platform: str, product_name: str = "", user_id: Optional[int] = None) -> str:
        """Get affiliate link to resell platform"""
        try:
            platform_urls = {
                "stockx": "https://stockx.com/search",
                "goat": "https://www.goat.com/search",
                "stadium_goods": "https://www.stadiumgoods.com/search",
                "flight_club": "https://www.flightclub.com/search",
                "consignment": "https://www.consignment.com/search"
            }
            
            base_url = platform_urls.get(platform.lower())
            if not base_url:
                return "https://stockx.com"  # Default fallback
            
            # Add search parameters if product name provided
            if product_name:
                search_params = {"q": product_name}
                base_url += "?" + urlencode(search_params)
            
            # Add affiliate parameters
            if platform.lower() in ["stockx", "goat", "stadium_goods"]:
                retailer_enum = getattr(Retailer, platform.upper(), None)
                if retailer_enum:
                    return self.get_affiliate_link(base_url, retailer_enum, user_id)
            
            return base_url
            
        except Exception as e:
            logger.error(f"Error generating resell platform link: {e}")
            return "https://stockx.com"
    
    def get_rakuten_link(self, partner: str, product_url: str, user_id: Optional[int] = None) -> str:
        """Generate Rakuten affiliate link"""
        try:
            partner_info = self.rakuten_partners.get(partner.lower())
            if not partner_info:
                return product_url
            
            rakuten_params = {
                "id": partner_info["code"],
                "mid": "1",
                "murl": product_url,
                "u1": f"sneakerdropbot_{user_id}" if user_id else "sneakerdropbot"
            }
            
            rakuten_url = partner_info["base_url"] + "?" + urlencode(rakuten_params)
            
            # Track click
            if user_id:
                asyncio.create_task(self._track_rakuten_click(user_id, partner, product_url))
            
            return rakuten_url
            
        except Exception as e:
            logger.error(f"Error generating Rakuten link: {e}")
            return product_url
    
    async def _track_click(self, user_id: int, retailer: Retailer, original_url: str, affiliate_url: str):
        """Track affiliate click"""
        try:
            click = AffiliateClick(
                user_id=user_id,
                retailer=retailer.value,
                original_url=original_url,
                affiliate_url=affiliate_url,
                clicked_at=datetime.utcnow(),
                ip_address="",  # Would be filled by webhook
                user_agent=""   # Would be filled by webhook
            )
            
            await db_manager.add_affiliate_click(click)
            
        except Exception as e:
            logger.error(f"Error tracking click: {e}")
    
    async def _track_rakuten_click(self, user_id: int, partner: str, product_url: str):
        """Track Rakuten affiliate click"""
        try:
            click = AffiliateClick(
                user_id=user_id,
                retailer=f"rakuten_{partner}",
                original_url=product_url,
                affiliate_url=f"rakuten_redirect_{partner}",
                clicked_at=datetime.utcnow()
            )
            
            await db_manager.add_affiliate_click(click)
            
        except Exception as e:
            logger.error(f"Error tracking Rakuten click: {e}")
    
    async def process_conversion(self, order_data: Dict) -> Optional[AffiliateEarning]:
        """Process affiliate conversion/sale"""
        try:
            # Extract data from order webhook
            user_ref = order_data.get("user_ref")
            retailer = order_data.get("retailer")
            order_value = float(order_data.get("order_value", 0))
            order_id = order_data.get("order_id")
            
            if not all([user_ref, retailer, order_value, order_id]):
                logger.warning("Incomplete conversion data received")
                return None
            
            user_id = int(user_ref.split("_")[-1]) if "_" in user_ref else int(user_ref)
            
            # Get commission rate
            retailer_enum = getattr(Retailer, retailer.upper(), None)
            if not retailer_enum:
                return None
            
            affiliate_info = self.affiliate_codes.get(retailer_enum)
            if not affiliate_info:
                return None
            
            commission_rate = affiliate_info["commission_rate"]
            commission_amount = order_value * commission_rate
            
            # Create earning record
            earning = AffiliateEarning(
                user_id=user_id,
                retailer=retailer,
                order_id=order_id,
                order_value=order_value,
                commission_rate=commission_rate,
                commission_amount=commission_amount,
                status="pending",
                created_at=datetime.utcnow()
            )
            
            await db_manager.add_affiliate_earning(earning)
            
            logger.info(f"Processed conversion: {order_id} for ${commission_amount:.2f}")
            return earning
            
        except Exception as e:
            logger.error(f"Error processing conversion: {e}")
            return None
    
    async def get_affiliate_statistics(self, days: int = 30) -> Dict:
        """Get affiliate performance statistics"""
        try:
            stats = await db_manager.get_affiliate_statistics(days)
            
            # Calculate performance metrics
            total_clicks = stats.get("total_clicks", 0)
            total_conversions = stats.get("total_conversions", 0)
            total_revenue = stats.get("total_revenue", 0)
            total_commission = stats.get("total_commission", 0)
            
            conversion_rate = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0
            avg_order_value = (total_revenue / total_conversions) if total_conversions > 0 else 0
            
            return {
                "total_clicks": total_clicks,
                "total_conversions": total_conversions,
                "conversion_rate": round(conversion_rate, 2),
                "total_revenue": round(total_revenue, 2),
                "total_commission": round(total_commission, 2),
                "avg_order_value": round(avg_order_value, 2),
                "commission_rate": round((total_commission / total_revenue * 100) if total_revenue > 0 else 0, 2),
                "top_retailers": stats.get("top_retailers", []),
                "daily_breakdown": stats.get("daily_breakdown", [])
            }
            
        except Exception as e:
            logger.error(f"Error getting affiliate statistics: {e}")
            return {}
    
    async def get_user_earnings(self, user_id: int) -> Dict:
        """Get user's contribution to affiliate earnings"""
        try:
            user_stats = await db_manager.get_user_affiliate_stats(user_id)
            
            return {
                "total_clicks": user_stats.get("total_clicks", 0),
                "total_conversions": user_stats.get("total_conversions", 0),
                "total_contributed_revenue": user_stats.get("total_revenue", 0),
                "commission_generated": user_stats.get("commission_generated", 0),
                "favorite_retailers": user_stats.get("favorite_retailers", []),
                "last_purchase": user_stats.get("last_purchase")
            }
            
        except Exception as e:
            logger.error(f"Error getting user earnings for {user_id}: {e}")
            return {}
    
    def get_deep_link(self, retailer: Retailer, product_id: str = "", category: str = "") -> str:
        """Generate deep link to specific product or category"""
        try:
            deep_link_patterns = {
                Retailer.NIKE: {
                    "base": "https://www.nike.com",
                    "product": "/t/{product_id}",
                    "category": "/{category}"
                },
                Retailer.ADIDAS: {
                    "base": "https://www.adidas.com/us",
                    "product": "/{product_id}.html",
                    "category": "/{category}"
                },
                Retailer.FOOTLOCKER: {
                    "base": "https://www.footlocker.com",
                    "product": "/product/{product_id}",
                    "category": "/{category}"
                },
                Retailer.STOCKX: {
                    "base": "https://stockx.com",
                    "product": "/{product_id}",
                    "category": "/search?s={category}"
                }
            }
            
            pattern = deep_link_patterns.get(retailer)
            if not pattern:
                return self.affiliate_codes.get(retailer, {}).get("base_url", "")
            
            base_url = pattern["base"]
            
            if product_id and "product" in pattern:
                url = base_url + pattern["product"].format(product_id=product_id)
            elif category and "category" in pattern:
                url = base_url + pattern["category"].format(category=category)
            else:
                url = base_url
            
            # Add affiliate parameters
            return self.get_affiliate_link(url, retailer)
            
        except Exception as e:
            logger.error(f"Error generating deep link: {e}")
            return ""
    
    async def track_referral(self, referrer_id: int, referred_id: int) -> bool:
        """Track user referral for potential rewards"""
        try:
            # This could be expanded to include referral bonuses
            referral_data = {
                "referrer_id": referrer_id,
                "referred_id": referred_id,
                "referral_date": datetime.utcnow(),
                "status": "active"
            }
            
            await db_manager.add_referral(referral_data)
            
            # Could trigger referral rewards here
            await self._process_referral_reward(referrer_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error tracking referral: {e}")
            return False
    
    async def _process_referral_reward(self, referrer_id: int):
        """Process referral rewards (e.g., free premium days)"""
        try:
            # Give referrer 3 days of premium
            await db_manager.add_bonus_premium_days(referrer_id, 3)
            
            logger.info(f"Awarded 3 premium days to user {referrer_id} for referral")
            
        except Exception as e:
            logger.error(f"Error processing referral reward: {e}")
    
    def get_retailer_commission_rate(self, retailer: Retailer) -> float:
        """Get commission rate for a retailer"""
        affiliate_info = self.affiliate_codes.get(retailer)
        return affiliate_info["commission_rate"] if affiliate_info else 0.0
    
    async def optimize_affiliate_links(self):
        """Optimize affiliate link performance based on data"""
        try:
            # Get performance data
            stats = await self.get_affiliate_statistics(days=7)
            
            # Analyze which retailers perform best
            top_retailers = stats.get("top_retailers", [])
            
            # Could implement logic to:
            # - Prioritize high-converting retailers
            # - A/B test different affiliate parameters
            # - Adjust commission tracking
            
            logger.info("Affiliate link optimization completed")
            
        except Exception as e:
            logger.error(f"Error optimizing affiliate links: {e}")


# Global affiliate manager instance
affiliate_manager = AffiliateManager()
