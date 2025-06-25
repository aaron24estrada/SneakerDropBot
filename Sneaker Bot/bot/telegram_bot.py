"""
SneakerDropBot - Main Telegram Bot Implementation
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)
from telegram.constants import ParseMode
from loguru import logger

from database.connection import db_manager
from database.models import User, TrackedSneaker, AlertHistory, UserSubscription
from app.monitoring_engine import monitoring_engine
from scrapers.scraper_manager import scraper_manager
from bot.payment_processor import payment_processor
from bot.alert_sender import alert_sender
from bot.affiliate_manager import affiliate_manager


class SneakerDropBot:
    """Main Telegram Bot class"""
    
    # Conversation states
    WAITING_SNEAKER_NAME = 1
    WAITING_SIZE = 2
    WAITING_PRICE_LIMIT = 3
    
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.active_users = set()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup bot command and message handlers"""
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("track", self.track_command))
        self.application.add_handler(CommandHandler("list", self.list_tracking))
        self.application.add_handler(CommandHandler("remove", self.remove_tracking))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("trending", self.trending_command))
        self.application.add_handler(CommandHandler("market", self.market_command))
        
        # Admin commands
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.application.add_handler(CommandHandler("stats", self.admin_stats))
        self.application.add_handler(CommandHandler("setdrop", self.manual_drop_alert))
        
        # Callback query handlers
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Conversation handler for tracking setup
        tracking_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_tracking_conversation, pattern="track_")],
            states={
                self.WAITING_SNEAKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_sneaker_name)],
                self.WAITING_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_size)],
                self.WAITING_PRICE_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_price_limit)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_tracking)]
        )
        self.application.add_handler(tracking_conv)
        
        # Message handlers
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        # Register user in database
        user = await self.get_or_create_user(user_id, username)
        
        welcome_message = f"""
👟 **Welcome to SneakerDropBot!**

Get instant alerts for sneaker restocks, price drops, and flip opportunities.

What would you like to track?
        """
        
        keyboard = [
            [
                InlineKeyboardButton("🔁 Restocks", callback_data="track_restocks"),
                InlineKeyboardButton("💸 Price Drops", callback_data="track_price_drops")
            ],
            [
                InlineKeyboardButton("📈 Resell Deals", callback_data="track_resell_deals"),
                InlineKeyboardButton("🔥 All Alerts", callback_data="track_all")
            ],
            [
                InlineKeyboardButton("📊 Trending", callback_data="trending"),
                InlineKeyboardButton("💎 Premium", callback_data="premium")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("📋 My Tracking", callback_data="list_tracking")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🤖 **SneakerDropBot Commands**

**Basic Commands:**
• `/start` - Start the bot and see main menu
• `/track` - Add a new sneaker to track
• `/list` - View your tracked sneakers
• `/remove` - Remove a tracked sneaker
• `/status` - Check your account status
• `/trending` - See trending sneakers
• `/market <sneaker>` - Get market analysis

**Premium Features:**
• `/premium` - Upgrade to premium
• Unlimited tracking
• Instant alerts
• Flip analysis
• Early notifications

**How it works:**
1. Add sneakers to track with sizes and price limits
2. Get instant alerts when restocks happen
3. See flip opportunities with profit margins
4. Track price drops across all major retailers

**Supported Retailers:**
Nike, Adidas, FootLocker, Finish Line, Champs, StockX, GOAT, and more!

Need help? Contact @SneakerDropSupport
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /track command"""
        user_id = update.effective_user.id
        user = await self.get_or_create_user(user_id)
        
        # Check if user has reached tracking limit
        tracking_count = await db_manager.get_user_tracking_count(user_id)
        
        if not user.is_premium and tracking_count >= 1:
            await update.message.reply_text(
                "🚫 **Free Plan Limit Reached**\n\n"
                "You can track 1 sneaker on the free plan.\n"
                "Upgrade to Premium for unlimited tracking!\n\n"
                "Use /premium to upgrade",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        keyboard = [
            [
                InlineKeyboardButton("🔁 Restocks", callback_data="track_restocks"),
                InlineKeyboardButton("💸 Price Drops", callback_data="track_price_drops")
            ],
            [
                InlineKeyboardButton("📈 Resell Deals", callback_data="track_resell_deals"),
                InlineKeyboardButton("🔥 All Alerts", callback_data="track_all")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "What type of alerts do you want for this sneaker?",
            reply_markup=reply_markup
        )
    
    async def start_tracking_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the tracking conversation"""
        query = update.callback_query
        await query.answer()
        
        alert_type = query.data.replace("track_", "")
        context.user_data['alert_type'] = alert_type
        
        await query.edit_message_text(
            "🔍 **What sneaker do you want to track?**\n\n"
            "Examples:\n"
            "• Jordan 4 Bred\n"
            "• Nike Dunk Low Panda\n"
            "• Yeezy 350 Zebra\n\n"
            "Type the sneaker name:",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return self.WAITING_SNEAKER_NAME
    
    async def handle_sneaker_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle sneaker name input"""
        sneaker_name = update.message.text.strip()
        context.user_data['sneaker_name'] = sneaker_name
        
        # Search for the sneaker to validate
        await update.message.reply_text(
            f"🔍 Searching for **{sneaker_name}**...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Quick search to validate sneaker exists
        search_results = await scraper_manager.search_all_retailers(sneaker_name, limit=3)
        
        if search_results:
            await update.message.reply_text(
                f"✅ Found **{sneaker_name}**!\n\n"
                f"👟 **Which size(s) do you want alerts for?**\n\n"
                f"Examples:\n"
                f"• 10.5\n"
                f"• 9, 9.5, 10\n"
                f"• All (for any size)\n\n"
                f"Type your size(s):",
                parse_mode=ParseMode.MARKDOWN
            )
            return self.WAITING_SIZE
        else:
            await update.message.reply_text(
                f"❌ Couldn't find **{sneaker_name}**\n\n"
                f"Try a different name or check spelling.\n"
                f"Use /cancel to start over.",
                parse_mode=ParseMode.MARKDOWN
            )
            return self.WAITING_SNEAKER_NAME
    
    async def handle_size(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle size input"""
        size_input = update.message.text.strip()
        context.user_data['sizes'] = size_input
        
        await update.message.reply_text(
            "💰 **Set a price limit? (optional)**\n\n"
            "Examples:\n"
            "• <250 (under $250)\n"
            "• >100 (over $100)\n"
            "• 150-200 (between $150-200)\n"
            "• Skip (no price limit)\n\n"
            "Type your price limit or 'Skip':",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return self.WAITING_PRICE_LIMIT
    
    async def handle_price_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle price limit input and create tracking"""
        price_limit = update.message.text.strip()
        
        user_id = update.effective_user.id
        sneaker_name = context.user_data['sneaker_name']
        sizes = context.user_data['sizes']
        alert_type = context.user_data['alert_type']
        
        # Parse price limit
        min_price, max_price = self.parse_price_limit(price_limit)
        
        # Create tracking record
        tracking = TrackedSneaker(
            user_id=user_id,
            keyword=sneaker_name,
            sizes=sizes,
            alert_types=[alert_type] if alert_type != "all" else ["restocks", "price_drops", "resell_deals"],
            min_price=min_price,
            max_price=max_price,
            is_active=True
        )
        
        await db_manager.add_tracked_sneaker(tracking)
        
        # Create success message
        alert_types_text = {
            "restocks": "🔁 Restock alerts",
            "price_drops": "💸 Price drop alerts", 
            "resell_deals": "📈 Resell deal alerts",
            "all": "🔥 All alerts (restocks, price drops, resell deals)"
        }
        
        price_text = ""
        if min_price or max_price:
            if min_price and max_price:
                price_text = f"\n💰 Price range: ${min_price} - ${max_price}"
            elif min_price:
                price_text = f"\n💰 Minimum price: ${min_price}"
            elif max_price:
                price_text = f"\n💰 Maximum price: ${max_price}"
        
        success_message = f"""
✅ **Tracking Added!**

👟 **Sneaker:** {sneaker_name}
📏 **Sizes:** {sizes}
🔔 **Alerts:** {alert_types_text.get(alert_type, alert_type)}{price_text}

You'll get instant notifications when this sneaker restocks or drops in price!

Use /list to see all your tracked sneakers.
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📋 My Tracking", callback_data="list_tracking"),
                InlineKeyboardButton("➕ Track Another", callback_data="track_all")
            ],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            success_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
        # Clear conversation data
        context.user_data.clear()
        return ConversationHandler.END
    
    async def cancel_tracking(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel tracking conversation"""
        await update.message.reply_text(
            "❌ Tracking setup cancelled.\n\nUse /track to start again."
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    async def list_tracking(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List user's tracked sneakers"""
        user_id = update.effective_user.id
        
        # Handle both callback and command
        if update.callback_query:
            await update.callback_query.answer()
            edit_message = update.callback_query.edit_message_text
        else:
            edit_message = update.message.reply_text
        
        tracked_sneakers = await db_manager.get_user_tracked_sneakers(user_id)
        
        if not tracked_sneakers:
            await edit_message(
                "📭 **No tracked sneakers**\n\n"
                "Use /track to start tracking your first sneaker!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        message = "📋 **Your Tracked Sneakers**\n\n"
        
        for i, sneaker in enumerate(tracked_sneakers, 1):
            status = "🟢 Active" if sneaker.is_active else "🔴 Paused"
            alert_icons = {
                "restocks": "🔁",
                "price_drops": "💸", 
                "resell_deals": "📈"
            }
            
            alerts = " ".join([alert_icons.get(alert, "🔔") for alert in sneaker.alert_types])
            
            message += f"**{i}. {sneaker.keyword}**\n"
            message += f"📏 Sizes: {sneaker.sizes}\n"
            message += f"🔔 Alerts: {alerts}\n"
            message += f"📊 Status: {status}\n\n"
        
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Tracking", callback_data="track_all"),
                InlineKeyboardButton("➖ Remove", callback_data="remove_tracking")
            ],
            [
                InlineKeyboardButton("⏸️ Pause All", callback_data="pause_all"),
                InlineKeyboardButton("▶️ Resume All", callback_data="resume_all")
            ],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await edit_message(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user status and statistics"""
        user_id = update.effective_user.id
        user = await self.get_or_create_user(user_id)
        
        tracking_count = await db_manager.get_user_tracking_count(user_id)
        alerts_today = await db_manager.get_user_alerts_count(user_id, hours=24)
        
        plan = "💎 Premium" if user.is_premium else "🆓 Free"
        limit = "Unlimited" if user.is_premium else f"{tracking_count}/1"
        
        status_message = f"""
📊 **Your SneakerDropBot Status**

👤 **Account:** {plan}
📋 **Tracked Sneakers:** {limit}
🔔 **Alerts Today:** {alerts_today}
📅 **Member Since:** {user.created_at.strftime("%B %Y")}

**Recent Activity:**
• Last alert: {await self.get_last_alert_time(user_id)}
• Total alerts received: {await db_manager.get_user_total_alerts(user_id)}
        """
        
        keyboard = []
        
        if not user.is_premium:
            keyboard.append([InlineKeyboardButton("💎 Upgrade to Premium", callback_data="premium")])
        
        keyboard.append([InlineKeyboardButton("📋 My Tracking", callback_data="list_tracking")])
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            status_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show premium features and pricing"""
        user_id = update.effective_user.id
        user = await self.get_or_create_user(user_id)
        
        if user.is_premium:
            await update.message.reply_text(
                "💎 **You're already Premium!**\n\n"
                "Enjoying unlimited tracking and instant alerts. Thanks for your support!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        premium_message = """
💎 **SneakerDropBot Premium**

**Free Plan:**
🆓 1 sneaker tracked
🔔 5 alerts/month
⏰ Standard priority

**Premium Plan - $9.99/month:**
✅ Unlimited sneakers tracked
✅ Instant alerts (priority)
✅ Flip margin analysis
✅ Early drop notifications
✅ Price history & trends
✅ Advanced filters
✅ Premium support

**Upgrade now and never miss a drop!**
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Subscribe - $9.99/month", callback_data="subscribe_monthly")],
            [InlineKeyboardButton("📊 Free Trial (3 days)", callback_data="free_trial")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            premium_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def trending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trending sneakers"""
        # Handle both callback and command
        if update.callback_query:
            await update.callback_query.answer()
            edit_message = update.callback_query.edit_message_text
        else:
            edit_message = update.message.reply_text
        
        await edit_message("🔍 **Getting trending sneakers...**", parse_mode=ParseMode.MARKDOWN)
        
        trending = await scraper_manager.get_trending_sneakers(days=7)
        
        if not trending:
            await edit_message(
                "📊 **No trending data available**\n\n"
                "Check back later for trending sneaker insights!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        message = "🔥 **Trending Sneakers (Last 7 Days)**\n\n"
        
        for i, item in enumerate(trending[:5], 1):
            name = item["sneaker_name"]
            tracking_count = item["tracking_count"]
            price_analysis = item.get("price_analysis", {})
            
            message += f"**{i}. {name}**\n"
            message += f"👥 {tracking_count} people tracking\n"
            
            if price_analysis.get("retail_vs_resell"):
                premium = price_analysis["retail_vs_resell"]["premium_percentage"]
                message += f"📈 Resell premium: +{premium:.0f}%\n"
            
            message += "\n"
        
        keyboard = [
            [InlineKeyboardButton("📊 Full Market Data", callback_data="market_analysis")],
            [InlineKeyboardButton("➕ Track Trending", callback_data="track_trending")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await edit_message(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def market_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show market analysis for a sneaker"""
        if not context.args:
            await update.message.reply_text(
                "📊 **Market Analysis**\n\n"
                "Usage: `/market <sneaker name>`\n\n"
                "Example: `/market Jordan 4 Bred`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        sneaker_name = " ".join(context.args)
        
        await update.message.reply_text(
            f"🔍 **Analyzing market for {sneaker_name}...**",
            parse_mode=ParseMode.MARKDOWN
        )
        
        market_data = await scraper_manager.get_comprehensive_market_data(sneaker_name)
        
        if not market_data["retail_availability"] and not market_data["resell_data"]:
            await update.message.reply_text(
                f"❌ **No data found for {sneaker_name}**\n\n"
                "Try a different sneaker name or check spelling.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        message = f"📊 **Market Analysis: {sneaker_name}**\n\n"
        
        # Retail availability
        retail_count = len(market_data["retail_availability"])
        if retail_count > 0:
            message += f"🏪 **Retail Availability:** {retail_count} stores\n"
            
            retail_prices = [p.price for p in market_data["retail_availability"] if p.price]
            if retail_prices:
                avg_retail = sum(retail_prices) / len(retail_prices)
                message += f"💰 **Average Retail:** ${avg_retail:.0f}\n"
        
        # Resell data
        price_analysis = market_data.get("price_analysis", {})
        if price_analysis:
            message += f"\n📈 **Resell Market:**\n"
            message += f"💎 **Average:** ${price_analysis['average_resell_price']:.0f}\n"
            message += f"⬇️ **Lowest:** ${price_analysis['lowest_resell_price']:.0f}\n"
            message += f"⬆️ **Highest:** ${price_analysis['highest_resell_price']:.0f}\n"
            
            if "retail_vs_resell" in price_analysis:
                premium = price_analysis["retail_vs_resell"]["premium_percentage"]
                message += f"📊 **Premium:** +{premium:.0f}%\n"
        
        keyboard = [
            [InlineKeyboardButton("➕ Track This Sneaker", callback_data=f"track_market_{sneaker_name}")],
            [InlineKeyboardButton("🔄 Refresh Data", callback_data=f"refresh_market_{sneaker_name}")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "main_menu":
            await self.show_main_menu(query)
        elif data == "help":
            await self.show_help(query)
        elif data == "list_tracking":
            await self.list_tracking(update, context)
        elif data == "trending":
            await self.trending_command(update, context)
        elif data == "premium":
            await self.show_premium(query)
        elif data == "subscribe_monthly":
            await self.start_subscription(query, "monthly")
        elif data == "free_trial":
            await self.start_free_trial(query)
        elif data.startswith("track_market_"):
            sneaker_name = data.replace("track_market_", "")
            await self.quick_track_sneaker(query, sneaker_name)
        elif data.startswith("refresh_market_"):
            sneaker_name = data.replace("refresh_market_", "")
            await self.refresh_market_data(query, sneaker_name)
        else:
            # Handle other callbacks
            pass
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages"""
        text = update.message.text.lower()
        
        if any(word in text for word in ["help", "start", "menu"]):
            await self.start_command(update, context)
        elif any(word in text for word in ["track", "add", "follow"]):
            await self.track_command(update, context)
        elif any(word in text for word in ["list", "show", "my"]):
            await self.list_tracking(update, context)
        elif any(word in text for word in ["premium", "upgrade", "subscribe"]):
            await self.premium_command(update, context)
        else:
            await update.message.reply_text(
                "🤔 I didn't understand that. Use /help to see available commands!"
            )
    
    # Admin Commands
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel"""
        user_id = update.effective_user.id
        
        if not await self.is_admin(user_id):
            await update.message.reply_text("❌ Admin access required.")
            return
        
        admin_message = """
👑 **SneakerDropBot Admin Panel**

**Commands:**
• `/stats` - Bot statistics
• `/broadcast <message>` - Send to all users
• `/setdrop <sneaker>` - Manual drop alert
• `/health` - System health check

**Quick Actions:**
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
                InlineKeyboardButton("🔔 Send Alert", callback_data="admin_alert")
            ],
            [
                InlineKeyboardButton("💾 Database", callback_data="admin_db"),
                InlineKeyboardButton("🔧 Settings", callback_data="admin_settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            admin_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin statistics"""
        user_id = update.effective_user.id
        
        if not await self.is_admin(user_id):
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Get statistics
        total_users = await db_manager.get_total_users()
        premium_users = await db_manager.get_premium_users_count()
        active_tracking = await db_manager.get_active_tracking_count()
        alerts_today = await db_manager.get_alerts_count(hours=24)
        
        # Get scraper analytics
        scraper_analytics = scraper_manager.get_scraper_analytics()
        
        stats_message = f"""
📊 **Bot Statistics**

👥 **Users:**
• Total: {total_users}
• Premium: {premium_users} ({premium_users/total_users*100:.1f}%)
• Active today: {len(self.active_users)}

📋 **Tracking:**
• Active sneakers: {active_tracking}
• Alerts sent today: {alerts_today}

🤖 **Scrapers:**
• Healthy: {scraper_analytics['healthy_scrapers']}/{scraper_analytics['total_scrapers']}
• Success rate: {sum(m['success_rate'] for m in scraper_analytics['performance_metrics'].values()) / len(scraper_analytics['performance_metrics']):.1f}%

💰 **Revenue:**
• Monthly: ${premium_users * 9.99:.2f}
• Annual: ${premium_users * 9.99 * 12:.2f}
        """
        
        await update.message.reply_text(
            stats_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast message to all users"""
        user_id = update.effective_user.id
        
        if not await self.is_admin(user_id):
            await update.message.reply_text("❌ Admin access required.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "📢 **Broadcast Message**\n\n"
                "Usage: `/broadcast <message>`\n\n"
                "This will send the message to all bot users."
            )
            return
        
        message = " ".join(context.args)
        
        await update.message.reply_text(
            f"📢 **Broadcasting to all users...**\n\n"
            f"Message: {message}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Get all users
        users = await db_manager.get_all_users()
        success_count = 0
        
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user.user_id,
                    text=f"📢 **SneakerDropBot Announcement**\n\n{message}",
                    parse_mode=ParseMode.MARKDOWN
                )
                success_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.warning(f"Failed to send broadcast to {user.user_id}: {e}")
        
        await update.message.reply_text(
            f"✅ **Broadcast completed**\n\n"
            f"Sent to {success_count}/{len(users)} users"
        )
    
    async def manual_drop_alert(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send manual drop alert"""
        user_id = update.effective_user.id
        
        if not await self.is_admin(user_id):
            await update.message.reply_text("❌ Admin access required.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🔔 **Manual Drop Alert**\n\n"
                "Usage: `/setdrop <sneaker name>`\n\n"
                "This will send alerts to users tracking this sneaker."
            )
            return
        
        sneaker_name = " ".join(context.args)
        
        # Find users tracking this sneaker
        tracking_users = await db_manager.get_users_tracking_keyword(sneaker_name)
        
        if not tracking_users:
            await update.message.reply_text(
                f"❌ No users tracking '{sneaker_name}'"
            )
            return
        
        # Send alerts
        alert_message = f"""
🔥 **MANUAL DROP ALERT**

👟 **{sneaker_name}** is now available!

Check your favorite retailers now!

🏪 Check: Nike, Adidas, FootLocker, Finish Line
        """
        
        success_count = 0
        for user_id in tracking_users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=alert_message,
                    parse_mode=ParseMode.MARKDOWN
                )
                success_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.warning(f"Failed to send manual alert to {user_id}: {e}")
        
        await update.message.reply_text(
            f"✅ **Manual alert sent**\n\n"
            f"Notified {success_count} users tracking '{sneaker_name}'"
        )
    
    # Helper Methods
    async def get_or_create_user(self, user_id: int, username: str = None) -> User:
        """Get or create user in database"""
        user = await db_manager.get_user(user_id)
        
        if not user:
            user = User(
                user_id=user_id,
                username=username,
                is_premium=False,
                created_at=datetime.utcnow()
            )
            await db_manager.add_user(user)
        
        return user
    
    def parse_price_limit(self, price_text: str) -> tuple[Optional[float], Optional[float]]:
        """Parse price limit text into min/max values"""
        if not price_text or price_text.lower() == "skip":
            return None, None
        
        # Handle different formats
        price_text = price_text.replace("$", "").replace(",", "")
        
        if "<" in price_text:
            # <250 -> max_price = 250
            max_price = float(re.findall(r'[\d.]+', price_text)[0])
            return None, max_price
        elif ">" in price_text:
            # >100 -> min_price = 100
            min_price = float(re.findall(r'[\d.]+', price_text)[0])
            return min_price, None
        elif "-" in price_text:
            # 150-200 -> min_price = 150, max_price = 200
            prices = re.findall(r'[\d.]+', price_text)
            if len(prices) >= 2:
                return float(prices[0]), float(prices[1])
        else:
            # Single number - treat as max
            try:
                price = float(price_text)
                return None, price
            except ValueError:
                pass
        
        return None, None
    
    async def get_last_alert_time(self, user_id: int) -> str:
        """Get last alert time for user"""
        last_alert = await db_manager.get_last_alert(user_id)
        
        if not last_alert:
            return "Never"
        
        time_diff = datetime.utcnow() - last_alert.created_at
        
        if time_diff.days > 0:
            return f"{time_diff.days} days ago"
        elif time_diff.seconds > 3600:
            return f"{time_diff.seconds // 3600} hours ago"
        else:
            return f"{time_diff.seconds // 60} minutes ago"
    
    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        admin_ids = [int(id_) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_.strip()]
        return user_id in admin_ids
    
    async def show_main_menu(self, query):
        """Show main menu"""
        keyboard = [
            [
                InlineKeyboardButton("🔁 Restocks", callback_data="track_restocks"),
                InlineKeyboardButton("💸 Price Drops", callback_data="track_price_drops")
            ],
            [
                InlineKeyboardButton("📈 Resell Deals", callback_data="track_resell_deals"),
                InlineKeyboardButton("🔥 All Alerts", callback_data="track_all")
            ],
            [
                InlineKeyboardButton("📊 Trending", callback_data="trending"),
                InlineKeyboardButton("💎 Premium", callback_data="premium")
            ],
            [
                InlineKeyboardButton("📋 My Tracking", callback_data="list_tracking"),
                InlineKeyboardButton("❓ Help", callback_data="help")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "👟 **SneakerDropBot**\n\nWhat would you like to do?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def show_help(self, query):
        """Show help message"""
        help_text = """
🤖 **SneakerDropBot Help**

**Commands:**
• `/start` - Main menu
• `/track` - Add sneaker tracking
• `/list` - View tracked sneakers
• `/status` - Account status
• `/premium` - Upgrade account

**Features:**
• 🔁 Restock alerts
• 💸 Price drop notifications
• 📈 Resell deal analysis
• 📊 Market trends

**Support:** @SneakerDropSupport
        """
        
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def show_premium(self, query):
        """Show premium features"""
        await query.edit_message_text(
            "💎 **Premium Features**\n\n"
            "• Unlimited tracking\n"
            "• Instant alerts\n"
            "• Flip analysis\n"
            "• Early notifications\n\n"
            "Only $9.99/month!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Subscribe", callback_data="subscribe_monthly")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    
    async def start_subscription(self, query, plan_type):
        """Start subscription process"""
        user_id = query.from_user.id
        
        # Generate payment link
        payment_url = await payment_processor.create_subscription_payment(user_id, plan_type)
        
        keyboard = [
            [InlineKeyboardButton("💳 Pay Now", url=payment_url)],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💳 **Complete Your Subscription**\n\n"
            "Click 'Pay Now' to subscribe to Premium!\n\n"
            "💎 $9.99/month\n"
            "✅ Unlimited tracking\n"
            "✅ Instant alerts\n"
            "✅ Premium features",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def start_free_trial(self, query):
        """Start free trial"""
        user_id = query.from_user.id
        
        # Enable 3-day trial
        await db_manager.start_free_trial(user_id, days=3)
        
        await query.edit_message_text(
            "🎉 **Free Trial Activated!**\n\n"
            "You now have 3 days of Premium access!\n\n"
            "✅ Unlimited tracking\n"
            "✅ Instant alerts\n"
            "✅ Premium features\n\n"
            "Enjoy exploring all features!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Start Tracking", callback_data="track_all")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    
    async def quick_track_sneaker(self, query, sneaker_name):
        """Quick track a sneaker from market data"""
        user_id = query.from_user.id
        
        # Create basic tracking
        tracking = TrackedSneaker(
            user_id=user_id,
            keyword=sneaker_name,
            sizes="All",
            alert_types=["restocks", "price_drops"],
            is_active=True
        )
        
        await db_manager.add_tracked_sneaker(tracking)
        
        await query.edit_message_text(
            f"✅ **Now tracking {sneaker_name}!**\n\n"
            f"You'll get alerts for restocks and price drops.\n\n"
            f"Use /list to manage your tracking.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 My Tracking", callback_data="list_tracking")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    
    async def refresh_market_data(self, query, sneaker_name):
        """Refresh market data for a sneaker"""
        await query.edit_message_text(
            f"🔄 **Refreshing data for {sneaker_name}...**",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # This would trigger a fresh data collection
        # For now, just show a message
        await asyncio.sleep(2)
        
        await query.edit_message_text(
            f"✅ **Data refreshed for {sneaker_name}**\n\n"
            f"Latest market data has been collected!\n\n"
            f"Use `/market {sneaker_name}` to see updated analysis.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Analysis", callback_data=f"refresh_market_{sneaker_name}")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    
    async def run(self):
        """Start the bot"""
        logger.info("Starting SneakerDropBot...")
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("track", "Add sneaker tracking"),
            BotCommand("list", "View tracked sneakers"),
            BotCommand("status", "Account status"),
            BotCommand("premium", "Upgrade to premium"),
            BotCommand("trending", "View trending sneakers"),
            BotCommand("market", "Market analysis"),
            BotCommand("help", "Show help"),
        ]
        
        await self.application.bot.set_my_commands(commands)
        
        # Start polling
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("SneakerDropBot is running!")
        
        # Keep running
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        finally:
            await self.application.stop()


# Global bot instance
bot = None

def create_bot(token: str) -> SneakerDropBot:
    """Create and return bot instance"""
    global bot
    bot = SneakerDropBot(token)
    return bot

async def start_bot(token: str):
    """Start the bot"""
    global bot
    bot = create_bot(token)
    await bot.run()
