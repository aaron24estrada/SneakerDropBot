"""
Simplified Telegram Bot for Render.com deployment
Core functionality without heavy dependencies
"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
from loguru import logger


class SimpleTelegramBot:
    """Simplified Telegram bot for basic functionality"""
    
    def __init__(self, token: str, scraper_manager=None, db_manager=None):
        self.token = token
        self.scraper_manager = scraper_manager
        self.db_manager = db_manager
        self.application = Application.builder().token(token).build()
        self.is_polling = False
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup bot command and message handlers"""
        # Basic commands
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("track", self.track_command))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        
        # Admin commands  
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        
        # Callback handlers
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Message handlers
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def initialize(self):
        """Initialize the bot"""
        try:
            await self.application.initialize()
            
            # Set bot commands
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("help", "Show help"),
                BotCommand("status", "Show status"),
                BotCommand("track", "Track a sneaker"),
                BotCommand("premium", "Upgrade to premium"),
            ]
            await self.application.bot.set_my_commands(commands)
            
            logger.info("✅ Bot initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Bot initialization failed: {e}")
            raise
    
    async def start_polling(self):
        """Start bot polling"""
        try:
            await self.application.start()
            await self.application.updater.start_polling()
            self.is_polling = True
            
            logger.info("✅ Bot polling started")
            
            # Keep running
            while self.is_polling:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Bot polling failed: {e}")
            self.is_polling = False
            raise
    
    async def stop(self):
        """Stop the bot"""
        try:
            self.is_polling = False
            if self.application.updater:
                await self.application.updater.stop()
            await self.application.stop()
            logger.info("✅ Bot stopped")
        except Exception as e:
            logger.error(f"❌ Bot stop failed: {e}")
    
    def is_running(self) -> bool:
        """Check if bot is running"""
        return self.is_polling
    
    async def process_update(self, update_data: Dict[str, Any]):
        """Process webhook update"""
        try:
            update = Update.de_json(update_data, self.application.bot)
            await self.application.process_update(update)
        except Exception as e:
            logger.error(f"❌ Update processing failed: {e}")
            raise
    
    # Command handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        welcome_message = f"""
👟 **Welcome to SneakerDropBot!**

Hello {user.first_name}! 

I'm your sneaker drop alert bot. Here's what I can do:

🔔 **Alert you** when sneakers restock
💰 **Track prices** and notify of drops  
📈 **Find flip opportunities** in the resell market
💎 **Premium features** for serious sneaker enthusiasts

**Quick Start:**
• Use /track to add a sneaker to monitor
• Use /status to see your account info
• Use /premium to unlock all features

Ready to never miss a drop again? 🚀
        """
        
        keyboard = [
            [
                InlineKeyboardButton("🔁 Track Sneaker", callback_data="track"),
                InlineKeyboardButton("📊 My Status", callback_data="status")
            ],
            [
                InlineKeyboardButton("💎 Go Premium", callback_data="premium"),
                InlineKeyboardButton("❓ Help", callback_data="help")
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
        help_message = """
🆘 **SneakerDropBot Help**

**Commands:**
• `/start` - Welcome message and main menu
• `/track` - Add a sneaker to track
• `/status` - View your account status
• `/premium` - Upgrade to premium features

**How it works:**
1. Tell me which sneaker you want to track
2. I'll monitor major retailers for restocks
3. Get instant alerts when your size is available
4. Premium users get flip opportunity alerts

**Supported Retailers:**
• Nike & Nike SNKRS
• Adidas & Yeezy Supply  
• Foot Locker
• Finish Line
• StockX & GOAT (resell)

**Premium Features:**
• Unlimited tracking
• Instant alerts (no delays)
• Flip opportunity analysis
• Early drop notifications

Need help? Contact support! 📧
        """
        
        await update.message.reply_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        
        # Get real user data
        if self.db_manager:
            user = await self.db_manager.get_or_create_user(
                user_id, 
                update.effective_user.username
            )
            tracked_sneakers = await self.db_manager.get_user_tracked_sneakers(user_id)
            
            plan = "💎 Premium" if user.get('is_premium', False) else "🆓 Free"
            max_tracked = "Unlimited" if user.get('is_premium', False) else "1"
            tracked_count = len(tracked_sneakers)
            member_since = user.get('created_at', datetime.now()).strftime("%B %Y")
            alerts_received = user.get('alerts_received', 0)
            
            status_message = f"""
📊 **Your SneakerDropBot Status**

👤 **Account:** {plan}
📋 **Tracked Sneakers:** {tracked_count}/{max_tracked}
🔔 **Total Alerts Received:** {alerts_received}
📅 **Member Since:** {member_since}
            """
            
            if tracked_sneakers:
                status_message += "\n**Your tracked sneakers:**\n"
                for sneaker in tracked_sneakers[:3]:  # Show first 3
                    name = sneaker.get('sneaker_name', 'Unknown')
                    size = sneaker.get('size', 'Any')
                    status_message += f"• {name} (Size: {size})\n"
                
                if len(tracked_sneakers) > 3:
                    status_message += f"• ... and {len(tracked_sneakers) - 3} more\n"
            
            if not user.get('is_premium', False):
                status_message += "\n**Upgrade to Premium for:**\n"
                status_message += "• ✅ Unlimited tracking\n"
                status_message += "• ✅ Instant alerts\n"
                status_message += "• ✅ Flip opportunities\n"
                status_message += "• ✅ Early access notifications\n"
        else:
            # Fallback if no database
            status_message = f"""
📊 **Your SneakerDropBot Status**

👤 **Account:** 🆓 Free Plan
📋 **Tracked Sneakers:** 0/1
🔔 **Alerts Today:** 0
📅 **Member Since:** {datetime.now().strftime("%B %Y")}

**Upgrade to Premium for:**
• ✅ Unlimited tracking
• ✅ Instant alerts  
• ✅ Flip opportunities
• ✅ Early access notifications
            """
        
        keyboard = [
            [InlineKeyboardButton("💎 Upgrade to Premium", callback_data="premium")],
            [InlineKeyboardButton("🔁 Track Sneaker", callback_data="track")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            status_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /track command"""
        user_id = update.effective_user.id
        
        # Get user from database
        if self.db_manager:
            user = await self.db_manager.get_or_create_user(
                user_id, 
                update.effective_user.username
            )
            
            # Check if user can track more sneakers
            tracked_sneakers = await self.db_manager.get_user_tracked_sneakers(user_id)
            max_tracked = 10 if user.get('is_premium', False) else 1
            
            if len(tracked_sneakers) >= max_tracked:
                message = f"""
🚫 **Tracking Limit Reached**

You're currently tracking {len(tracked_sneakers)}/{max_tracked} sneakers.

{'Premium users get unlimited tracking!' if not user.get('is_premium') else 'You have reached your premium limit.'}

**Your tracked sneakers:**
"""
                for sneaker in tracked_sneakers:
                    message += f"• {sneaker.get('sneaker_name', 'Unknown')} (Size: {sneaker.get('size', 'Any')})\n"
                
                if not user.get('is_premium'):
                    message += "\n💎 Upgrade to Premium for unlimited tracking!"
                
                keyboard = []
                if not user.get('is_premium'):
                    keyboard.append([InlineKeyboardButton("💎 Upgrade to Premium", callback_data="premium")])
                
                reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                
                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
        
        # Show tracking instructions
        track_message = f"""
🔍 **Track a Sneaker**

To track a sneaker, just tell me:
1. **Sneaker name** (e.g., "Jordan 4 Bred")
2. **Your size** (e.g., "10.5" or "All sizes")
3. **Price limit** (optional, e.g., "Under $250")

**Example:**
"Track Jordan 4 Bred size 10.5 under $220"

**What I'll monitor:**
• ✅ Restocks at major retailers (Nike, Adidas, StockX)
• ✅ Price drops
• ✅ Resell opportunities (Premium)

**Supported retailers:**
• Nike & Nike SNKRS
• Adidas 
• StockX (resell prices)

Start by telling me which sneaker you want! 👟
        """
        
        keyboard = [
            [InlineKeyboardButton("🔍 Search Popular Sneakers", callback_data="search_popular")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            track_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        premium_message = """
💎 **SneakerDropBot Premium**

**Unlock the full potential:**

🆓 **Free Plan:**
• 1 sneaker tracked
• 5 alerts per month
• Basic notifications

💎 **Premium Plan ($9.99/month):**
• ✅ **Unlimited** sneaker tracking
• ✅ **Instant** alerts (no delays)
• ✅ **Flip opportunity** analysis
• ✅ **Early access** notifications
• ✅ **Price drop** predictions
• ✅ **Priority** customer support

**Why upgrade?**
Never miss drops worth hundreds in resell value! Premium users consistently secure limited releases.

Ready to upgrade? 🚀
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Subscribe Now ($9.99/mo)", callback_data="subscribe")],
            [InlineKeyboardButton("🆓 Try 7 Days Free", callback_data="trial")],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="start")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            premium_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        user_id = update.effective_user.id
        
        # Basic admin check (implement proper admin system later)
        admin_message = """
🔧 **Admin Panel**

**System Status:**
• 🟢 Bot: Running
• 🟢 Database: Connected
• 🟡 Scrapers: Limited (Render deployment)

**Quick Stats:**
• Total Users: 0
• Premium Users: 0
• Alerts Sent Today: 0

**Available Commands:**
• `/admin stats` - Detailed statistics
• `/admin broadcast <message>` - Send message to all users
• `/admin health` - System health check

Note: Full admin features available in production deployment.
        """
        
        await update.message.reply_text(
            admin_message,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "start":
            await self.start_command(update, context)
        elif data == "help":
            await self.help_command(update, context)
        elif data == "status":
            await self.status_command(update, context)
        elif data == "track":
            await self.track_command(update, context)
        elif data == "premium":
            await self.premium_command(update, context)
        elif data == "subscribe":
            await query.edit_message_text(
                "💳 **Subscription Setup**\n\nPayment integration coming soon! For now, contact support to upgrade manually.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == "trial":
            await query.edit_message_text(
                "🆓 **Free Trial**\n\nFree trial activation coming soon! Premium features will be enabled automatically.",
                parse_mode=ParseMode.MARKDOWN
            )
        elif data == "search_popular":
            await self._handle_popular_search(query)
        elif data.startswith("price_"):
            sneaker_name = data.replace("price_", "").replace("_", " ")
            await self._handle_price_check(query, sneaker_name)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular text messages"""
        text = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Check if this looks like a tracking request
        if self._is_tracking_request(text):
            await self._handle_tracking_request(update, text)
        else:
            # Simple keyword detection for other cases
            text_lower = text.lower()
            if any(word in text_lower for word in ["track", "monitor", "follow"]):
                response = "🔍 To track a sneaker, tell me the sneaker name and size like:\n'Track Jordan 4 Bred size 10.5'"
            elif any(word in text_lower for word in ["premium", "upgrade", "subscribe"]):
                response = "💎 Interested in premium? Use /premium to see all the benefits!"
            elif any(word in text_lower for word in ["help", "support"]):
                response = "🆘 Need help? Use /help to see all available commands!"
            elif any(word in text_lower for word in ["search", "find"]):
                await self._handle_search_request(update, text)
                return
            else:
                response = "🤔 I didn't understand that. Use /help to see what I can do, or try the main menu with /start!"
            
            await update.message.reply_text(response)
    
    def _is_tracking_request(self, text: str) -> bool:
        """Check if text looks like a tracking request"""
        text_lower = text.lower()
        tracking_keywords = ["track", "monitor", "follow", "watch"]
        return any(keyword in text_lower for keyword in tracking_keywords)
    
    async def _handle_tracking_request(self, update: Update, text: str):
        """Handle sneaker tracking request"""
        try:
            user_id = update.effective_user.id
            
            # Parse the tracking request
            parsed = self._parse_tracking_text(text)
            
            if not parsed['sneaker_name']:
                await update.message.reply_text(
                    "🤔 I couldn't understand which sneaker you want to track. Try:\n'Track Jordan 4 Bred size 10.5'"
                )
                return
            
            # Check if user can track more sneakers
            if self.db_manager:
                user = await self.db_manager.get_or_create_user(user_id, update.effective_user.username)
                tracked_sneakers = await self.db_manager.get_user_tracked_sneakers(user_id)
                max_tracked = 10 if user.get('is_premium', False) else 1
                
                if len(tracked_sneakers) >= max_tracked:
                    await update.message.reply_text(
                        f"🚫 You've reached your tracking limit ({max_tracked} sneakers). Upgrade to Premium for unlimited tracking!"
                    )
                    return
                
                # Add the sneaker to tracking
                success = await self.db_manager.add_tracked_sneaker(user_id, {
                    'name': parsed['sneaker_name'],
                    'size': parsed['size'],
                    'price_limit': parsed['price_limit']
                })
                
                if success:
                    message = f"""
✅ **Tracking Added Successfully!**

👟 **Sneaker:** {parsed['sneaker_name']}
📏 **Size:** {parsed['size'] or 'Any size'}
💰 **Price Limit:** ${parsed['price_limit']} or less" if parsed['price_limit'] else "No limit"

I'll monitor major retailers and alert you when it's available!
                    """
                    
                    # Try to search for the sneaker immediately
                    if self.scraper_manager:
                        await update.message.reply_text("🔍 Searching for current availability...")
                        
                        try:
                            results = await self.scraper_manager.search_sneakers(parsed['sneaker_name'], max_results=3)
                            
                            if results:
                                message += f"\n\n🔍 **Current availability found:**\n"
                                for result in results:
                                    status = "✅ In Stock" if result.get('in_stock', False) else "❌ Out of Stock"
                                    price_text = f"${result.get('price')}" if result.get('price') else "Price not available"
                                    message += f"• {result.get('retailer')}: {status} - {price_text}\n"
                            else:
                                message += "\n\n🔍 **No current availability found.** I'll keep monitoring!"
                                
                        except Exception as e:
                            logger.error(f"Search error: {e}")
                            message += "\n\n🔍 **Search temporarily unavailable.** I'll keep monitoring!"
                    
                    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ Failed to add tracking. Please try again.")
            else:
                await update.message.reply_text("❌ Database not available. Please try again later.")
                
        except Exception as e:
            logger.error(f"Tracking request error: {e}")
            await update.message.reply_text("❌ Something went wrong. Please try again.")
    
    def _parse_tracking_text(self, text: str) -> Dict[str, Any]:
        """Parse tracking text to extract sneaker name, size, and price limit"""
        import re
        
        text_lower = text.lower()
        
        # Remove tracking keywords
        for keyword in ["track", "monitor", "follow", "watch"]:
            text_lower = text_lower.replace(keyword, "").strip()
        
        # Extract size (look for "size X" or "sz X")
        size = None
        size_match = re.search(r'(?:size|sz)\s+([^\s]+)', text_lower)
        if size_match:
            size = size_match.group(1)
            text_lower = text_lower.replace(size_match.group(0), "").strip()
        
        # Extract price limit (look for "under $X" or "< $X" or "$X max")
        price_limit = None
        price_patterns = [
            r'under\s+\$?(\d+)',
            r'<\s+\$?(\d+)', 
            r'\$?(\d+)\s+max',
            r'below\s+\$?(\d+)',
            r'less\s+than\s+\$?(\d+)'
        ]
        
        for pattern in price_patterns:
            price_match = re.search(pattern, text_lower)
            if price_match:
                try:
                    price_limit = float(price_match.group(1))
                    text_lower = text_lower.replace(price_match.group(0), "").strip()
                    break
                except ValueError:
                    pass
        
        # Clean up remaining text as sneaker name
        sneaker_name = text_lower.strip()
        
        # Remove extra whitespace
        sneaker_name = re.sub(r'\s+', ' ', sneaker_name)
        
        return {
            'sneaker_name': sneaker_name if sneaker_name else None,
            'size': size,
            'price_limit': price_limit
        }
    
    async def _handle_search_request(self, update: Update, text: str):
        """Handle sneaker search request"""
        try:
            if not self.scraper_manager:
                await update.message.reply_text("🔍 Search temporarily unavailable. Please try again later.")
                return
            
            # Extract search query
            search_query = text.lower().replace('search', '').replace('find', '').strip()
            
            if not search_query:
                await update.message.reply_text("🔍 What sneaker would you like me to search for?")
                return
            
            await update.message.reply_text(f"🔍 Searching for '{search_query}'...")
            
            results = await self.scraper_manager.search_sneakers(search_query, max_results=5)
            
            if results:
                message = f"🔍 **Search Results for '{search_query}':**\n\n"
                
                for i, result in enumerate(results, 1):
                    name = result.get('name', 'Unknown')
                    retailer = result.get('retailer', 'Unknown')
                    price = result.get('price')
                    status = "✅ In Stock" if result.get('in_stock', False) else "❌ Out of Stock"
                    
                    price_text = f"${price}" if price else "Price N/A"
                    
                    message += f"{i}. **{name}**\n"
                    message += f"   📍 {retailer} | {price_text} | {status}\n\n"
                
                message += "Want to track any of these? Use:\n'Track [sneaker name] size [your size]'"
                
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    f"😔 No results found for '{search_query}'. Try a different search or check the spelling."
                )
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            await update.message.reply_text("❌ Search failed. Please try again later.")
    
    async def send_alert(self, alert: Dict[str, Any]):
        """Send alert to user"""
        try:
            user_id = alert.get('user_id')
            if not user_id:
                return
            
            # Create alert message
            message = alert.get('message', '')
            if not message:
                message = self._format_alert_message(alert)
            
            # Create inline keyboard with buy link
            keyboard = []
            if alert.get('url'):
                keyboard.append([
                    InlineKeyboardButton("🛒 Buy Now", url=alert['url']),
                    InlineKeyboardButton("📊 Check Price", callback_data=f"price_{alert.get('sneaker_name', '').replace(' ', '_')}")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            # Send alert
            await self.application.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
            logger.info(f"✅ Alert sent to user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to send alert: {e}")
    
    def _format_alert_message(self, alert: Dict[str, Any]) -> str:
        """Format alert message"""
        name = alert.get('sneaker_name', 'Sneaker')
        retailer = alert.get('retailer', 'Store')
        price = alert.get('price')
        alert_type = alert.get('alert_type', 'restock')
        
        if alert_type == 'restock':
            emoji = "🔥"
            action = "back in stock"
        elif alert_type == 'price_drop':
            emoji = "💰"
            action = "price dropped"
        elif alert_type == 'flip':
            emoji = "📈"
            action = "flip opportunity"
        else:
            emoji = "🔔"
            action = "available"
        
        if price:
            return f"{emoji} **{name}** is {action} at **{retailer}** for **${price}**!"
        else:
            return f"{emoji} **{name}** is {action} at **{retailer}**!"
    
    async def _handle_popular_search(self, query):
        """Handle popular sneakers search"""
        try:
            popular_sneakers = [
                "Jordan 4 Bred",
                "Yeezy 350 Cream",
                "Dunk Low Panda",
                "Jordan 1 Chicago",
                "Yeezy 700 Wave Runner"
            ]
            
            if self.scraper_manager:
                # Search for one popular sneaker as example
                results = await self.scraper_manager.search_sneakers(popular_sneakers[0], max_results=3)
                
                message = "🔥 **Popular Sneakers:**\n\n"
                for sneaker in popular_sneakers:
                    message += f"• {sneaker}\n"
                
                if results:
                    message += f"\n**Current availability for {popular_sneakers[0]}:**\n"
                    for result in results:
                        status = "✅" if result.get('in_stock', False) else "❌"
                        price = f"${result.get('price')}" if result.get('price') else "N/A"
                        message += f"{status} {result.get('retailer')}: {price}\n"
                
                message += "\nTo track any sneaker, just tell me:\n'Track [sneaker name] size [your size]'"
            else:
                message = "🔥 **Popular Sneakers:**\n\n"
                for sneaker in popular_sneakers:
                    message += f"• {sneaker}\n"
                message += "\nTo track any sneaker, use:\n'Track [sneaker name] size [your size]'"
            
            await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Popular search error: {e}")
            await query.edit_message_text(
                "❌ Unable to load popular sneakers right now. Try searching for a specific sneaker!",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def _handle_price_check(self, query, sneaker_name: str):
        """Handle price check request"""
        try:
            if not self.scraper_manager:
                await query.edit_message_text(
                    "🔍 Price check temporarily unavailable.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            await query.edit_message_text(
                f"🔍 Checking prices for {sneaker_name}...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            results = await self.scraper_manager.search_sneakers(sneaker_name, max_results=5)
            
            if results:
                message = f"💰 **Price Check: {sneaker_name}**\n\n"
                
                for result in results:
                    retailer = result.get('retailer', 'Unknown')
                    price = result.get('price')
                    status = "✅ Available" if result.get('in_stock', False) else "❌ Out of Stock"
                    
                    if price:
                        message += f"**{retailer}:** ${price} - {status}\n"
                    else:
                        message += f"**{retailer}:** Price N/A - {status}\n"
                
                message += f"\nWant to track {sneaker_name}? Tell me:\n'Track {sneaker_name} size [your size]'"
            else:
                message = f"😔 No current pricing found for {sneaker_name}. Try a different sneaker or check back later."
            
            await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            logger.error(f"Price check error: {e}")
            await query.edit_message_text(
                "❌ Price check failed. Please try again later.",
                parse_mode=ParseMode.MARKDOWN
            )
