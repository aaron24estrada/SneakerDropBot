"""
Alert sending system for SneakerDropBot
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum
import random

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from loguru import logger

from database.connection import db_manager
from database.models import SneakerProduct, TrackedSneaker, AlertHistory, User, ResellData
from bot.affiliate_manager import affiliate_manager


class AlertType(Enum):
    RESTOCK = "restock"
    PRICE_DROP = "price_drop"
    RESELL_DEAL = "resell_deal"
    FLIP_OPPORTUNITY = "flip_opportunity"
    EARLY_ACCESS = "early_access"


class AlertSender:
    """Handle sending alerts to users via Telegram"""
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
        self.rate_limit_delay = 0.03  # 30ms between messages
        self.alert_cooldown = 300  # 5 minutes between same alerts to same user
        self.daily_limits = {
            "free": 5,
            "premium": 1000
        }
    
    async def send_restock_alert(self, product: SneakerProduct, users: List[int]) -> int:
        """Send restock alert to users"""
        sent_count = 0
        
        try:
            # Create alert message
            message = self._create_restock_message(product)
            
            # Send to each user
            for user_id in users:
                try:
                    # Check if user can receive alerts
                    if not await self._can_send_alert(user_id, AlertType.RESTOCK):
                        continue
                    
                    # Check cooldown
                    if await self._is_in_cooldown(user_id, product.name, AlertType.RESTOCK):
                        continue
                    
                    # Send alert
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=self._create_restock_keyboard(product)
                    )
                    
                    # Log alert
                    await self._log_alert(user_id, product, AlertType.RESTOCK)
                    sent_count += 1
                    
                    # Rate limiting
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except TelegramError as e:
                    logger.warning(f"Failed to send restock alert to {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error sending restock alert to {user_id}: {e}")
                    continue
            
            logger.info(f"Sent restock alerts for {product.name} to {sent_count} users")
            
        except Exception as e:
            logger.error(f"Error in send_restock_alert: {e}")
        
        return sent_count
    
    async def send_price_drop_alert(self, product: SneakerProduct, old_price: float, users: List[int]) -> int:
        """Send price drop alert to users"""
        sent_count = 0
        
        try:
            message = self._create_price_drop_message(product, old_price)
            
            for user_id in users:
                try:
                    if not await self._can_send_alert(user_id, AlertType.PRICE_DROP):
                        continue
                    
                    if await self._is_in_cooldown(user_id, product.name, AlertType.PRICE_DROP):
                        continue
                    
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=self._create_price_drop_keyboard(product)
                    )
                    
                    await self._log_alert(user_id, product, AlertType.PRICE_DROP)
                    sent_count += 1
                    
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except TelegramError as e:
                    logger.warning(f"Failed to send price drop alert to {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error sending price drop alert to {user_id}: {e}")
                    continue
            
            logger.info(f"Sent price drop alerts for {product.name} to {sent_count} users")
            
        except Exception as e:
            logger.error(f"Error in send_price_drop_alert: {e}")
        
        return sent_count
    
    async def send_resell_deal_alert(self, retail_product: SneakerProduct, resell_data: ResellData, profit_margin: float, users: List[int]) -> int:
        """Send resell deal alert to users"""
        sent_count = 0
        
        try:
            message = self._create_resell_deal_message(retail_product, resell_data, profit_margin)
            
            for user_id in users:
                try:
                    # Check if user is premium (resell deals are premium feature)
                    user = await db_manager.get_user(user_id)
                    if not user or not user.is_premium:
                        continue
                    
                    if not await self._can_send_alert(user_id, AlertType.RESELL_DEAL):
                        continue
                    
                    if await self._is_in_cooldown(user_id, retail_product.name, AlertType.RESELL_DEAL):
                        continue
                    
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=self._create_resell_deal_keyboard(retail_product, resell_data)
                    )
                    
                    await self._log_alert(user_id, retail_product, AlertType.RESELL_DEAL)
                    sent_count += 1
                    
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except TelegramError as e:
                    logger.warning(f"Failed to send resell deal alert to {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error sending resell deal alert to {user_id}: {e}")
                    continue
            
            logger.info(f"Sent resell deal alerts for {retail_product.name} to {sent_count} users")
            
        except Exception as e:
            logger.error(f"Error in send_resell_deal_alert: {e}")
        
        return sent_count
    
    async def send_flip_opportunity_alert(self, opportunities: List[Dict], users: List[int]) -> int:
        """Send flip opportunity alerts to premium users"""
        sent_count = 0
        
        try:
            message = self._create_flip_opportunity_message(opportunities)
            
            for user_id in users:
                try:
                    # Only for premium users
                    user = await db_manager.get_user(user_id)
                    if not user or not user.is_premium:
                        continue
                    
                    if not await self._can_send_alert(user_id, AlertType.FLIP_OPPORTUNITY):
                        continue
                    
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=self._create_flip_opportunity_keyboard()
                    )
                    
                    # Log alert for first opportunity
                    if opportunities:
                        await self._log_alert(user_id, None, AlertType.FLIP_OPPORTUNITY, opportunities[0]["name"])
                    
                    sent_count += 1
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except TelegramError as e:
                    logger.warning(f"Failed to send flip opportunity alert to {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error sending flip opportunity alert to {user_id}: {e}")
                    continue
            
            logger.info(f"Sent flip opportunity alerts to {sent_count} users")
            
        except Exception as e:
            logger.error(f"Error in send_flip_opportunity_alert: {e}")
        
        return sent_count
    
    async def send_early_access_alert(self, product: SneakerProduct, access_url: str, users: List[int]) -> int:
        """Send early access alert to premium users"""
        sent_count = 0
        
        try:
            message = self._create_early_access_message(product, access_url)
            
            for user_id in users:
                try:
                    # Only for premium users
                    user = await db_manager.get_user(user_id)
                    if not user or not user.is_premium:
                        continue
                    
                    if not await self._can_send_alert(user_id, AlertType.EARLY_ACCESS):
                        continue
                    
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=self._create_early_access_keyboard(access_url)
                    )
                    
                    await self._log_alert(user_id, product, AlertType.EARLY_ACCESS)
                    sent_count += 1
                    
                    await asyncio.sleep(self.rate_limit_delay)
                    
                except TelegramError as e:
                    logger.warning(f"Failed to send early access alert to {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error sending early access alert to {user_id}: {e}")
                    continue
            
            logger.info(f"Sent early access alerts for {product.name} to {sent_count} users")
            
        except Exception as e:
            logger.error(f"Error in send_early_access_alert: {e}")
        
        return sent_count
    
    def _create_restock_message(self, product: SneakerProduct) -> str:
        """Create restock alert message"""
        emoji = "🔥" if "jordan" in product.name.lower() else "🔁"
        
        message = f"{emoji} **RESTOCK ALERT**\n\n"
        message += f"👟 **{product.name}** is back in stock!\n\n"
        
        if product.price:
            message += f"💰 **Price:** ${product.price:.2f}\n"
        
        message += f"🏪 **Store:** {product.retailer.value.replace('_', ' ').title()}\n"
        
        if product.sizes_available:
            sizes = [str(size.us_size) for size in product.sizes_available[:5]]
            if len(product.sizes_available) > 5:
                sizes.append("...")
            message += f"📏 **Sizes:** {', '.join(sizes)}\n"
        
        message += f"\n⚡ **Hurry! Limited stock available**"
        
        return message
    
    def _create_price_drop_message(self, product: SneakerProduct, old_price: float) -> str:
        """Create price drop alert message"""
        savings = old_price - product.price if product.price else 0
        savings_pct = (savings / old_price * 100) if old_price > 0 else 0
        
        message = f"💸 **PRICE DROP ALERT**\n\n"
        message += f"👟 **{product.name}**\n\n"
        message += f"🔻 **Was:** ~~${old_price:.2f}~~\n"
        message += f"💰 **Now:** **${product.price:.2f}**\n"
        message += f"💵 **Save:** ${savings:.2f} ({savings_pct:.0f}% off)\n\n"
        message += f"🏪 **Store:** {product.retailer.value.replace('_', ' ').title()}\n"
        
        if savings_pct >= 30:
            message += f"\n🚨 **HUGE DISCOUNT! Don't miss out!**"
        elif savings_pct >= 20:
            message += f"\n🔥 **Great deal! Limited time offer**"
        
        return message
    
    def _create_resell_deal_message(self, retail_product: SneakerProduct, resell_data: ResellData, profit_margin: float) -> str:
        """Create resell deal alert message"""
        message = f"📈 **FLIP OPPORTUNITY**\n\n"
        message += f"👟 **{retail_product.name}**\n\n"
        message += f"🛒 **Buy for:** ${retail_product.price:.2f}\n"
        message += f"💎 **Resell avg:** ${resell_data.price:.2f}\n"
        message += f"💰 **Profit:** ${resell_data.price - retail_product.price:.2f}\n"
        message += f"📊 **Margin:** +{profit_margin:.0f}%\n\n"
        message += f"🏪 **Buy from:** {retail_product.retailer.value.replace('_', ' ').title()}\n"
        message += f"💎 **Sell on:** {resell_data.platform.replace('_', ' ').title()}\n"
        
        if profit_margin >= 50:
            message += f"\n🚨 **HIGH PROFIT OPPORTUNITY!**"
        elif profit_margin >= 25:
            message += f"\n🔥 **Good flip potential**"
        
        return message
    
    def _create_flip_opportunity_message(self, opportunities: List[Dict]) -> str:
        """Create flip opportunity digest message"""
        message = f"🔥 **DAILY FLIP OPPORTUNITIES**\n\n"
        
        for i, opp in enumerate(opportunities[:3], 1):
            message += f"**{i}. {opp['name']}**\n"
            message += f"💰 Buy: ${opp['buy_price']:.2f} → Sell: ${opp['sell_price']:.2f}\n"
            message += f"📊 Margin: +{opp['margin']:.0f}%\n\n"
        
        if len(opportunities) > 3:
            message += f"*...and {len(opportunities) - 3} more opportunities*\n\n"
        
        message += f"💎 **Premium members only**"
        
        return message
    
    def _create_early_access_message(self, product: SneakerProduct, access_url: str) -> str:
        """Create early access alert message"""
        message = f"⚡ **EARLY ACCESS ALERT**\n\n"
        message += f"👟 **{product.name}**\n\n"
        message += f"🎯 **You have early access before the public drop!**\n\n"
        
        if product.price:
            message += f"💰 **Price:** ${product.price:.2f}\n"
        
        message += f"🏪 **Store:** {product.retailer.value.replace('_', ' ').title()}\n"
        message += f"⏰ **Limited time access**\n\n"
        message += f"💎 **Premium exclusive benefit**"
        
        return message
    
    def _create_restock_keyboard(self, product: SneakerProduct):
        """Create inline keyboard for restock alerts"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        # Get affiliate link
        buy_url = affiliate_manager.get_affiliate_link(product.url, product.retailer)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Buy Now", url=buy_url)],
            [
                InlineKeyboardButton("📊 Market Data", callback_data=f"market_{product.name}"),
                InlineKeyboardButton("🔔 More Alerts", callback_data="track_similar")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _create_price_drop_keyboard(self, product: SneakerProduct):
        """Create inline keyboard for price drop alerts"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        buy_url = affiliate_manager.get_affiliate_link(product.url, product.retailer)
        
        keyboard = [
            [InlineKeyboardButton("🛒 Buy Now", url=buy_url)],
            [
                InlineKeyboardButton("📈 Price History", callback_data=f"price_history_{product.name}"),
                InlineKeyboardButton("🔔 Set Lower Alert", callback_data=f"lower_alert_{product.name}")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _create_resell_deal_keyboard(self, retail_product: SneakerProduct, resell_data: ResellData):
        """Create inline keyboard for resell deal alerts"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        buy_url = affiliate_manager.get_affiliate_link(retail_product.url, retail_product.retailer)
        resell_url = affiliate_manager.get_resell_platform_link(resell_data.platform)
        
        keyboard = [
            [
                InlineKeyboardButton("🛒 Buy Retail", url=buy_url),
                InlineKeyboardButton("💎 Check Resell", url=resell_url)
            ],
            [
                InlineKeyboardButton("📊 Full Analysis", callback_data=f"flip_analysis_{retail_product.name}"),
                InlineKeyboardButton("💡 Flip Guide", callback_data="flip_guide")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _create_flip_opportunity_keyboard(self):
        """Create inline keyboard for flip opportunity alerts"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [
                InlineKeyboardButton("📊 View All Opportunities", callback_data="view_all_flips"),
                InlineKeyboardButton("⚙️ Flip Settings", callback_data="flip_settings")
            ],
            [InlineKeyboardButton("💡 Flip Guide", callback_data="flip_guide")]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _create_early_access_keyboard(self, access_url: str):
        """Create inline keyboard for early access alerts"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = [
            [InlineKeyboardButton("⚡ Get Early Access", url=access_url)],
            [
                InlineKeyboardButton("📱 Share Access", callback_data="share_access"),
                InlineKeyboardButton("🔔 More Premium", callback_data="premium_features")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    async def _can_send_alert(self, user_id: int, alert_type: AlertType) -> bool:
        """Check if user can receive alerts"""
        try:
            user = await db_manager.get_user(user_id)
            if not user:
                return False
            
            # Check daily alert limit
            alerts_today = await db_manager.get_user_alerts_count(user_id, hours=24)
            limit = self.daily_limits["premium"] if user.is_premium else self.daily_limits["free"]
            
            if alerts_today >= limit:
                return False
            
            # Check if user has tracking for this alert type
            # (This would be implemented based on your tracking system)
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking if can send alert to {user_id}: {e}")
            return False
    
    async def _is_in_cooldown(self, user_id: int, sneaker_name: str, alert_type: AlertType) -> bool:
        """Check if alert is in cooldown period"""
        try:
            last_alert = await db_manager.get_last_alert_for_sneaker(
                user_id, sneaker_name, alert_type.value
            )
            
            if not last_alert:
                return False
            
            time_diff = datetime.utcnow() - last_alert.created_at
            return time_diff.total_seconds() < self.alert_cooldown
            
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return False
    
    async def _log_alert(self, user_id: int, product: Optional[SneakerProduct], alert_type: AlertType, sneaker_name: str = None):
        """Log alert to database"""
        try:
            alert = AlertHistory(
                user_id=user_id,
                sneaker_name=sneaker_name or (product.name if product else ""),
                alert_type=alert_type.value,
                retailer=product.retailer.value if product else "",
                price=product.price if product else None,
                created_at=datetime.utcnow()
            )
            
            await db_manager.add_alert_history(alert)
            
        except Exception as e:
            logger.error(f"Error logging alert: {e}")
    
    async def send_test_alert(self, user_id: int) -> bool:
        """Send test alert to user"""
        try:
            message = """
🧪 **Test Alert**

This is a test message from SneakerDropBot!

✅ Your alerts are working correctly
🔔 You'll receive notifications for your tracked sneakers
💎 Upgrade to Premium for unlimited alerts

Happy sneaker hunting! 👟
            """
            
            await self.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending test alert to {user_id}: {e}")
            return False
    
    async def get_alert_statistics(self) -> Dict[str, Any]:
        """Get alert sending statistics"""
        try:
            stats = await db_manager.get_alert_statistics()
            
            return {
                "total_alerts_sent": stats.get("total_alerts_sent", 0),
                "alerts_today": stats.get("alerts_today", 0),
                "alerts_this_week": stats.get("alerts_this_week", 0),
                "alert_types": stats.get("alert_types", {}),
                "top_sneakers": stats.get("top_sneakers", []),
                "success_rate": stats.get("success_rate", 0),
                "average_response_time": stats.get("average_response_time", 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting alert statistics: {e}")
            return {}


# Global alert sender instance (will be initialized with bot token)
alert_sender = None

def create_alert_sender(bot_token: str) -> AlertSender:
    """Create and return alert sender instance"""
    global alert_sender
    alert_sender = AlertSender(bot_token)
    return alert_sender
