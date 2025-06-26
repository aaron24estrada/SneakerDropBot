"""
Main Telegram Bot implementation
"""
import asyncio
from typing import Dict, Any
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, BotCommandScopeDefault
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from loguru import logger

from config.settings import settings
from database.connection import db_manager
from database.models import User, TrackedSneaker, AlertType, SneakerSize
from utils.helpers import generate_affiliate_link, format_price


class SneakerDropBot:
    """Main bot class"""
    
    def __init__(self):
        self.application = None
        self.user_states: Dict[int, Dict[str, Any]] = {}
    
    async def initialize(self):
        """Initialize the bot"""
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        
        # Register handlers
        await self._register_handlers()
        
        # Set bot commands
        await self._set_bot_commands()
        
        logger.info("Bot initialized successfully")
    
    async def _register_handlers(self):
        """Register all command and callback handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("track", self.track_command))
        self.application.add_handler(CommandHandler("myalerts", self.my_alerts_command))
        self.application.add_handler(CommandHandler("mystatus", self.my_status_command))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))
        
        # Admin commands
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # Callback query handlers
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Message handlers
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
    
    async def _set_bot_commands(self):
        """Set bot commands menu"""
        commands = [
            BotCommand("start", "🚀 Start the bot"),
            BotCommand("track", "👟 Track a new sneaker"),
            BotCommand("myalerts", "📋 View my tracked sneakers"),
            BotCommand("mystatus", "👤 View my account status"),
            BotCommand("premium", "⭐ Upgrade to Premium"),
            BotCommand("help", "❓ Get help"),
            BotCommand("cancel", "❌ Cancel current operation"),
        ]
        
        await self.application.bot.set_my_commands(
            commands, scope=BotCommandScopeDefault()
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        last_name = update.effective_user.last_name
        
        # Create or get user
        user = await db_manager.get_user(telegram_id)
        if not user:
            user = await db_manager.create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name
            )
            await db_manager.update_daily_analytics(new_signups=1)
        else:
            # Update last interaction
            await db_manager.update_user(telegram_id, {"last_interaction": user.updated_at})
        
        welcome_text = f"""
👟 **Welcome to SneakerDropBot!**

Hi {first_name}! I'll help you get instant alerts for:
🔁 **Sneaker Restocks**
💸 **Price Drops** 
📈 **Resell Opportunities**

Choose what you'd like to track:
        """
        
        keyboard = [
            [
                InlineKeyboardButton("🔁 Track Restocks", callback_data="track_restocks"),
                InlineKeyboardButton("💸 Price Drops", callback_data="track_price_drops")
            ],
            [InlineKeyboardButton("📈 Resell Deals", callback_data="track_resell_deals")],
            [InlineKeyboardButton("👤 My Status", callback_data="my_status")],
            [InlineKeyboardButton("⭐ Go Premium", callback_data="go_premium")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🤖 **SneakerDropBot Help**

**Commands:**
/start - Start the bot
/track - Track a new sneaker
/myalerts - View your tracked sneakers
/mystatus - Check your account status
/premium - Upgrade to Premium
/help - Show this help message
/cancel - Cancel current operation

**How to use:**
1️⃣ Use /track or click "Track Restocks/Price Drops"
2️⃣ Enter sneaker name (e.g., "Jordan 4 Bred")
3️⃣ Choose your size(s)
4️⃣ Set price limit (optional)
5️⃣ Get instant alerts! 🚨

**Free Plan:**
• Track 1 sneaker
• 5 alerts per month

**Premium Plan ($9.99/month):**
• Unlimited sneakers
• Unlimited alerts
• Priority notifications
• Flip margin analysis
• Early drop alerts

Need help? Contact @SneakerDropSupport
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /track command"""
        telegram_id = update.effective_user.id
        
        # Check if user can track more sneakers
        user = await db_manager.get_user(telegram_id)
        if not user:
            await update.message.reply_text("Please use /start first to create your account.")
            return
        
        if not user.can_track_more_sneakers(settings.max_free_tracked_sneakers):
            keyboard = [[InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="go_premium")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🚫 You've reached the limit of {settings.max_free_tracked_sneakers} tracked sneaker(s) for free users.\n\n"
                "Upgrade to Premium for unlimited tracking!",
                reply_markup=reply_markup
            )
            return
        
        # Start tracking flow
        self.user_states[telegram_id] = {"state": "waiting_for_sneaker_name"}
        
        await update.message.reply_text(
            "👟 **Track a New Sneaker**\n\n"
            "What sneaker would you like to track?\n"
            "Example: `Jordan 4 Bred`, `Yeezy 350 Cream`, `Air Max 90 Infrared`\n\n"
            "Type the sneaker name:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def my_alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /myalerts command"""
        telegram_id = update.effective_user.id
        
        tracked_sneakers = await db_manager.get_user_tracked_sneakers(telegram_id)
        
        if not tracked_sneakers:
            keyboard = [[InlineKeyboardButton("👟 Start Tracking", callback_data="track_restocks")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "📋 **Your Tracked Sneakers**\n\n"
                "You're not tracking any sneakers yet.\n"
                "Start tracking to get instant alerts!",
                reply_markup=reply_markup
            )
            return
        
        text = "📋 **Your Tracked Sneakers**\n\n"
        keyboard = []
        
        for i, sneaker in enumerate(tracked_sneakers, 1):
            sizes_text = "All sizes" if any(s.is_all_sizes for s in sneaker.sizes) else ", ".join([str(s.us_size) for s in sneaker.sizes if s.us_size])
            price_text = f" (max ${sneaker.max_price})" if sneaker.max_price else ""
            
            text += f"{i}. **{sneaker.keyword}**\n"
            text += f"   Sizes: {sizes_text}{price_text}\n"
            text += f"   Alerts: {', '.join([t.value.replace('_', ' ').title() for t in sneaker.alert_types])}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(f"📝 Edit #{i}", callback_data=f"edit_sneaker_{sneaker.id}"),
                InlineKeyboardButton(f"🗑️ Remove #{i}", callback_data=f"remove_sneaker_{sneaker.id}")
            ])
        
        keyboard.append([InlineKeyboardButton("➕ Track Another", callback_data="track_restocks")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def my_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /mystatus command"""
        telegram_id = update.effective_user.id
        user = await db_manager.get_user(telegram_id)
        
        if not user:
            await update.message.reply_text("Please use /start first to create your account.")
            return
        
        tracked_sneakers = await db_manager.get_user_tracked_sneakers(telegram_id)
        
        tier_emoji = "⭐" if user.is_premium() else "🆓"
        tier_text = "Premium" if user.is_premium() else "Free"
        
        status_text = f"""
👤 **Your Account Status**

{tier_emoji} **Plan:** {tier_text}
👟 **Tracked Sneakers:** {len(tracked_sneakers)}/{('Unlimited' if user.is_premium() else settings.max_free_tracked_sneakers)}
📨 **Alerts This Month:** {user.alerts_sent_this_month}/{('Unlimited' if user.is_premium() else settings.max_free_alerts_per_month)}
📅 **Member Since:** {user.created_at.strftime('%B %d, %Y')}
        """
        
        if user.is_premium() and user.subscription_expires_at:
            status_text += f"\n⏰ **Premium Expires:** {user.subscription_expires_at.strftime('%B %d, %Y')}"
        
        keyboard = []
        if not user.is_premium():
            keyboard.append([InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="go_premium")])
        
        keyboard.append([InlineKeyboardButton("👟 Track Sneaker", callback_data="track_restocks")])
        keyboard.append([InlineKeyboardButton("📋 My Alerts", callback_data="my_alerts")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        premium_text = """
⭐ **SneakerDropBot Premium**

**Premium Features:**
✅ Unlimited sneaker tracking
✅ Unlimited alerts per month
✅ Priority notifications (faster alerts)
✅ Flip margin analysis
✅ Early drop notifications
✅ Premium-only sneaker releases
✅ Advanced size filtering
✅ No ads

**Pricing:**
💰 $9.99/month
💎 $99.99/year (2 months free!)

**Payment Methods:**
💳 Credit/Debit Card
🌐 PayPal
        """
        
        keyboard = [
            [
                InlineKeyboardButton("💰 Monthly - $9.99", callback_data="premium_monthly"),
                InlineKeyboardButton("💎 Yearly - $99.99", callback_data="premium_yearly")
            ],
            [InlineKeyboardButton("❓ Learn More", callback_data="premium_info")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(premium_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command"""
        telegram_id = update.effective_user.id
        
        if telegram_id in self.user_states:
            del self.user_states[telegram_id]
            await update.message.reply_text("❌ Operation cancelled. Use /start to begin again.")
        else:
            await update.message.reply_text("No operation to cancel. Use /start to begin.")
    
    # Admin commands
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in settings.admin_telegram_ids:
            await update.message.reply_text("🚫 Access denied. Admin only.")
            return
        
        admin_text = """
🔧 **Admin Panel**

**Available Commands:**
/stats - View bot statistics
/broadcast <message> - Send message to all users
/premium <user_id> - Grant premium to user
/ban <user_id> - Ban a user
/unban <user_id> - Unban a user

**Quick Actions:**
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
            ],
            [
                InlineKeyboardButton("👥 Users", callback_data="admin_users"),
                InlineKeyboardButton("💰 Revenue", callback_data="admin_revenue")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command (admin only)"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in settings.admin_telegram_ids:
            await update.message.reply_text("🚫 Access denied. Admin only.")
            return
        
        # Get analytics data
        analytics = await db_manager.get_analytics(days=7)
        
        if not analytics:
            await update.message.reply_text("📊 No analytics data available yet.")
            return
        
        latest = analytics[0]
        
        stats_text = f"""
📊 **Bot Statistics**

**Today:**
👥 Total Users: {latest.total_users}
⭐ Premium Users: {latest.premium_users}
📨 Alerts Sent: {latest.alerts_sent}
🆕 New Signups: {latest.new_signups}
💰 Revenue: ${latest.revenue:.2f}

**Last 7 Days:**
📊 Total Alerts: {sum(a.alerts_sent for a in analytics)}
👥 New Users: {sum(a.new_signups for a in analytics)}
💰 Total Revenue: ${sum(a.revenue for a in analytics):.2f}
        """
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command (admin only)"""
        telegram_id = update.effective_user.id
        
        if telegram_id not in settings.admin_telegram_ids:
            await update.message.reply_text("🚫 Access denied. Admin only.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "📢 **Broadcast Message**\n\n"
                "Usage: `/broadcast <message>`\n"
                "Example: `/broadcast New feature released! 🎉`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        message = " ".join(context.args)
        
        # TODO: Implement broadcast functionality
        await update.message.reply_text(f"📢 Broadcasting message: {message}")
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        telegram_id = query.from_user.id
        
        if data.startswith("track_"):
            await self._handle_track_callback(query, data)
        elif data.startswith("premium_"):
            await self._handle_premium_callback(query, data)
        elif data.startswith("admin_"):
            await self._handle_admin_callback(query, data)
        elif data == "my_status":
            await self.my_status_command(update, context)
        elif data == "my_alerts":
            await self.my_alerts_command(update, context)
        elif data == "go_premium":
            await self.premium_command(update, context)
    
    async def _handle_track_callback(self, query, data):
        """Handle tracking-related callbacks"""
        telegram_id = query.from_user.id
        
        # Map callback data to alert types
        alert_type_map = {
            "track_restocks": [AlertType.RESTOCK],
            "track_price_drops": [AlertType.PRICE_DROP],
            "track_resell_deals": [AlertType.FLIP_OPPORTUNITY]
        }
        
        if data in alert_type_map:
            # Check if user can track more sneakers
            user = await db_manager.get_user(telegram_id)
            if not user.can_track_more_sneakers(settings.max_free_tracked_sneakers):
                keyboard = [[InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="go_premium")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"🚫 You've reached the limit of {settings.max_free_tracked_sneakers} tracked sneaker(s) for free users.\n\n"
                    "Upgrade to Premium for unlimited tracking!",
                    reply_markup=reply_markup
                )
                return
            
            # Store alert types and start tracking flow
            self.user_states[telegram_id] = {
                "state": "waiting_for_sneaker_name",
                "alert_types": alert_type_map[data]
            }
            
            type_text = data.replace("track_", "").replace("_", " ").title()
            
            await query.edit_message_text(
                f"👟 **Track {type_text}**\n\n"
                "What sneaker would you like to track?\n"
                "Example: `Jordan 4 Bred`, `Yeezy 350 Cream`, `Air Max 90 Infrared`\n\n"
                "Type the sneaker name:",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def _handle_premium_callback(self, query, data):
        """Handle premium-related callbacks"""
        # TODO: Implement Stripe payment integration
        await query.edit_message_text("💳 Payment integration coming soon!")
    
    async def _handle_admin_callback(self, query, data):
        """Handle admin-related callbacks"""
        telegram_id = query.from_user.id
        
        if telegram_id not in settings.admin_telegram_ids:
            await query.edit_message_text("🚫 Access denied. Admin only.")
            return
        
        if data == "admin_stats":
            await self.stats_command(query, None)
        # TODO: Implement other admin callbacks
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages"""
        telegram_id = update.effective_user.id
        text = update.message.text
        
        if telegram_id not in self.user_states:
            await update.message.reply_text(
                "I'm not sure what you mean. Use /start to see available options."
            )
            return
        
        state_data = self.user_states[telegram_id]
        state = state_data.get("state")
        
        if state == "waiting_for_sneaker_name":
            await self._handle_sneaker_name_input(update, text, state_data)
        elif state == "waiting_for_size":
            await self._handle_size_input(update, text, state_data)
        elif state == "waiting_for_price_limit":
            await self._handle_price_limit_input(update, text, state_data)
    
    async def _handle_sneaker_name_input(self, update, text, state_data):
        """Handle sneaker name input"""
        telegram_id = update.effective_user.id
        
        # Validate sneaker name
        if len(text.strip()) < 3:
            await update.message.reply_text(
                "⚠️ Sneaker name too short. Please enter at least 3 characters."
            )
            return
        
        state_data["sneaker_name"] = text.strip()
        state_data["state"] = "waiting_for_size"
        
        keyboard = [
            [
                InlineKeyboardButton("6", callback_data="size_6"),
                InlineKeyboardButton("6.5", callback_data="size_6.5"),
                InlineKeyboardButton("7", callback_data="size_7"),
                InlineKeyboardButton("7.5", callback_data="size_7.5")
            ],
            [
                InlineKeyboardButton("8", callback_data="size_8"),
                InlineKeyboardButton("8.5", callback_data="size_8.5"),
                InlineKeyboardButton("9", callback_data="size_9"),
                InlineKeyboardButton("9.5", callback_data="size_9.5")
            ],
            [
                InlineKeyboardButton("10", callback_data="size_10"),
                InlineKeyboardButton("10.5", callback_data="size_10.5"),
                InlineKeyboardButton("11", callback_data="size_11"),
                InlineKeyboardButton("11.5", callback_data="size_11.5")
            ],
            [
                InlineKeyboardButton("12", callback_data="size_12"),
                InlineKeyboardButton("13", callback_data="size_13"),
                InlineKeyboardButton("14", callback_data="size_14")
            ],
            [InlineKeyboardButton("👔 All Sizes", callback_data="size_all")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👟 Tracking: **{text}**\n\n"
            "👆 **Select Your Size(s):**\n"
            "You can also type multiple sizes separated by commas (e.g., `10, 10.5, 11`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def _handle_size_input(self, update, text, state_data):
        """Handle size input"""
        # Parse sizes from text input
        try:
            sizes = []
            for size_str in text.split(","):
                size_str = size_str.strip()
                if size_str.lower() in ["all", "any"]:
                    sizes = [SneakerSize(is_all_sizes=True)]
                    break
                else:
                    size_float = float(size_str)
                    if 4 <= size_float <= 18:  # Valid US shoe size range
                        sizes.append(SneakerSize(us_size=size_float))
            
            if not sizes:
                await update.message.reply_text(
                    "⚠️ Invalid size format. Please enter sizes like: `10, 10.5, 11` or `all`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            state_data["sizes"] = sizes
            state_data["state"] = "waiting_for_price_limit"
            
            keyboard = [
                [InlineKeyboardButton("✅ No Price Limit", callback_data="price_none")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "💰 **Set Price Limit (Optional)**\n\n"
                "Enter maximum price you want to pay (e.g., `250` for $250)\n"
                "Or click below to track at any price:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text(
                "⚠️ Invalid size format. Please enter sizes like: `10, 10.5, 11` or `all`",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def _handle_price_limit_input(self, update, text, state_data):
        """Handle price limit input"""
        telegram_id = update.effective_user.id
        
        try:
            if text.lower() in ["none", "no", "skip"]:
                max_price = None
            else:
                max_price = float(text.strip().replace("$", ""))
                if max_price <= 0:
                    await update.message.reply_text("⚠️ Price must be greater than 0.")
                    return
            
            # Create tracked sneaker
            tracked_sneaker = TrackedSneaker(
                user_telegram_id=telegram_id,
                keyword=state_data["sneaker_name"],
                sizes=state_data["sizes"],
                max_price=max_price,
                alert_types=state_data.get("alert_types", [AlertType.RESTOCK])
            )
            
            # Save to database
            await db_manager.add_tracked_sneaker(tracked_sneaker)
            
            # Clear user state
            del self.user_states[telegram_id]
            
            sizes_text = "All sizes" if any(s.is_all_sizes for s in tracked_sneaker.sizes) else ", ".join([str(s.us_size) for s in tracked_sneaker.sizes if s.us_size])
            price_text = f" under ${max_price}" if max_price else ""
            alert_types_text = ", ".join([t.value.replace("_", " ").title() for t in tracked_sneaker.alert_types])
            
            success_text = f"""
✅ **Tracking Started!**

👟 **Sneaker:** {tracked_sneaker.keyword}
👆 **Sizes:** {sizes_text}
💰 **Price:** Any{price_text}
🚨 **Alerts:** {alert_types_text}

I'll notify you instantly when this sneaker becomes available! 🚀

Use /myalerts to manage your tracked sneakers.
            """
            
            keyboard = [
                [InlineKeyboardButton("👟 Track Another", callback_data="track_restocks")],
                [InlineKeyboardButton("📋 My Alerts", callback_data="my_alerts")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                success_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text(
                "⚠️ Invalid price format. Please enter a number (e.g., `250` for $250) or type `none`."
            )
    
    async def start_polling(self):
        """Start the bot with polling"""
        logger.info("Starting bot with polling...")
        await self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    
    async def stop(self):
        """Stop the bot"""
        if self.application:
            await self.application.stop()
            logger.info("Bot stopped")


# Global bot instance
bot = SneakerDropBot()
