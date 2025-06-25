"""
Payment system integration with Stripe
"""
import stripe
from typing import Dict, Optional
from datetime import datetime, timedelta
from loguru import logger

from config.settings import settings
from database.connection import db_manager
from database.models import Payment, UserTier


class PaymentSystem:
    """Payment system for handling subscriptions"""
    
    def __init__(self):
        stripe.api_key = settings.stripe_secret_key
        self.webhook_secret = settings.stripe_webhook_secret
        
        # Pricing configuration
        self.pricing = {
            "monthly": {
                "amount": 999,  # $9.99 in cents
                "currency": "usd",
                "interval": "month",
                "interval_count": 1
            },
            "yearly": {
                "amount": 9999,  # $99.99 in cents
                "currency": "usd", 
                "interval": "year",
                "interval_count": 1
            }
        }
    
    async def create_payment_intent(self, user_telegram_id: int, plan: str) -> Dict:
        """Create a Stripe payment intent"""
        try:
            if plan not in self.pricing:
                raise ValueError(f"Invalid plan: {plan}")
            
            pricing = self.pricing[plan]
            
            # Create payment intent
            intent = stripe.PaymentIntent.create(
                amount=pricing["amount"],
                currency=pricing["currency"],
                automatic_payment_methods={"enabled": True},
                metadata={
                    "user_telegram_id": str(user_telegram_id),
                    "plan": plan,
                    "bot": "sneakerdropbot"
                }
            )
            
            # Save payment record
            payment = Payment(
                user_telegram_id=user_telegram_id,
                stripe_payment_intent_id=intent.id,
                amount=pricing["amount"] / 100,  # Convert cents to dollars
                currency=pricing["currency"],
                tier=UserTier.PREMIUM,
                duration_months=12 if plan == "yearly" else 1,
                status="pending"
            )
            
            await db_manager.create_payment(payment)
            
            logger.info(f"Created payment intent for user {user_telegram_id}, plan {plan}")
            
            return {
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.id,
                "amount": pricing["amount"],
                "currency": pricing["currency"]
            }
        
        except Exception as e:
            logger.error(f"Failed to create payment intent: {e}")
            raise
    
    async def handle_webhook(self, payload: str, signature: str) -> bool:
        """Handle Stripe webhook events"""
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            logger.info(f"Received Stripe webhook: {event['type']}")
            
            # Handle different event types
            if event['type'] == 'payment_intent.succeeded':
                await self._handle_payment_success(event['data']['object'])
            
            elif event['type'] == 'payment_intent.payment_failed':
                await self._handle_payment_failure(event['data']['object'])
            
            elif event['type'] == 'invoice.payment_succeeded':
                await self._handle_subscription_renewal(event['data']['object'])
            
            elif event['type'] == 'customer.subscription.deleted':
                await self._handle_subscription_cancellation(event['data']['object'])
            
            return True
        
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid webhook signature")
            return False
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return False
    
    async def _handle_payment_success(self, payment_intent: Dict):
        """Handle successful payment"""
        try:
            payment_intent_id = payment_intent['id']
            metadata = payment_intent.get('metadata', {})
            user_telegram_id = int(metadata.get('user_telegram_id'))
            plan = metadata.get('plan')
            
            # Update payment status
            await db_manager.update_payment_status(payment_intent_id, "succeeded")
            
            # Upgrade user to premium
            duration_months = 12 if plan == "yearly" else 1
            await db_manager.upgrade_user_to_premium(user_telegram_id, duration_months)
            
            # Send confirmation message to user
            await self._send_payment_confirmation(user_telegram_id, plan)
            
            # Update analytics
            amount = payment_intent['amount'] / 100
            await db_manager.update_daily_analytics(revenue=amount)
            
            logger.info(f"Payment successful for user {user_telegram_id}, plan {plan}")
        
        except Exception as e:
            logger.error(f"Error handling payment success: {e}")
    
    async def _handle_payment_failure(self, payment_intent: Dict):
        """Handle failed payment"""
        try:
            payment_intent_id = payment_intent['id']
            metadata = payment_intent.get('metadata', {})
            user_telegram_id = int(metadata.get('user_telegram_id'))
            
            # Update payment status
            await db_manager.update_payment_status(payment_intent_id, "failed")
            
            # Send failure notification to user
            await self._send_payment_failure_notification(user_telegram_id)
            
            logger.info(f"Payment failed for user {user_telegram_id}")
        
        except Exception as e:
            logger.error(f"Error handling payment failure: {e}")
    
    async def _handle_subscription_renewal(self, invoice: Dict):
        """Handle subscription renewal"""
        try:
            customer_id = invoice.get('customer')
            
            if not customer_id:
                return
            
            # Get customer information
            customer = stripe.Customer.retrieve(customer_id)
            metadata = customer.get('metadata', {})
            user_telegram_id = metadata.get('user_telegram_id')
            
            if user_telegram_id:
                user_telegram_id = int(user_telegram_id)
                
                # Extend premium subscription
                await db_manager.upgrade_user_to_premium(user_telegram_id, 1)
                
                # Send renewal confirmation
                await self._send_renewal_confirmation(user_telegram_id)
                
                logger.info(f"Subscription renewed for user {user_telegram_id}")
        
        except Exception as e:
            logger.error(f"Error handling subscription renewal: {e}")
    
    async def _handle_subscription_cancellation(self, subscription: Dict):
        """Handle subscription cancellation"""
        try:
            customer_id = subscription.get('customer')
            
            if not customer_id:
                return
            
            # Get customer information
            customer = stripe.Customer.retrieve(customer_id)
            metadata = customer.get('metadata', {})
            user_telegram_id = metadata.get('user_telegram_id')
            
            if user_telegram_id:
                user_telegram_id = int(user_telegram_id)
                
                # Downgrade user to free (at end of current period)
                # Note: We don't immediately downgrade, let the subscription expire naturally
                
                # Send cancellation confirmation
                await self._send_cancellation_confirmation(user_telegram_id)
                
                logger.info(f"Subscription cancelled for user {user_telegram_id}")
        
        except Exception as e:
            logger.error(f"Error handling subscription cancellation: {e}")
    
    async def _send_payment_confirmation(self, user_telegram_id: int, plan: str):
        """Send payment confirmation message to user"""
        try:
            from app.bot import bot
            
            plan_name = "Monthly" if plan == "monthly" else "Yearly"
            
            message = f"""
✅ **Payment Successful!**

🎉 Welcome to SneakerDropBot Premium!

**Plan:** {plan_name} Premium
**Status:** Active
**Benefits:**
• Unlimited sneaker tracking
• Unlimited alerts per month
• Priority notifications
• Flip margin analysis
• Early drop alerts

Start tracking your favorite sneakers with /track!
            """
            
            await bot.application.bot.send_message(
                chat_id=user_telegram_id,
                text=message.strip(),
                parse_mode="Markdown"
            )
        
        except Exception as e:
            logger.error(f"Failed to send payment confirmation to user {user_telegram_id}: {e}")
    
    async def _send_payment_failure_notification(self, user_telegram_id: int):
        """Send payment failure notification to user"""
        try:
            from app.bot import bot
            
            message = """
❌ **Payment Failed**

Your payment could not be processed. Please try again or contact support if the issue persists.

Use /premium to try again.
            """
            
            await bot.application.bot.send_message(
                chat_id=user_telegram_id,
                text=message.strip(),
                parse_mode="Markdown"
            )
        
        except Exception as e:
            logger.error(f"Failed to send payment failure notification to user {user_telegram_id}: {e}")
    
    async def _send_renewal_confirmation(self, user_telegram_id: int):
        """Send subscription renewal confirmation"""
        try:
            from app.bot import bot
            
            message = """
🔄 **Subscription Renewed**

Your SneakerDropBot Premium subscription has been renewed successfully!

Continue enjoying unlimited alerts and premium features.
            """
            
            await bot.application.bot.send_message(
                chat_id=user_telegram_id,
                text=message.strip(),
                parse_mode="Markdown"
            )
        
        except Exception as e:
            logger.error(f"Failed to send renewal confirmation to user {user_telegram_id}: {e}")
    
    async def _send_cancellation_confirmation(self, user_telegram_id: int):
        """Send subscription cancellation confirmation"""
        try:
            from app.bot import bot
            
            message = """
😢 **Subscription Cancelled**

Your SneakerDropBot Premium subscription has been cancelled.

You'll continue to have premium access until the end of your current billing period.

We'd love to have you back! Use /premium anytime to resubscribe.
            """
            
            await bot.application.bot.send_message(
                chat_id=user_telegram_id,
                text=message.strip(),
                parse_mode="Markdown"
            )
        
        except Exception as e:
            logger.error(f"Failed to send cancellation confirmation to user {user_telegram_id}: {e}")
    
    async def create_checkout_session(self, user_telegram_id: int, plan: str, success_url: str, cancel_url: str) -> str:
        """Create Stripe checkout session"""
        try:
            if plan not in self.pricing:
                raise ValueError(f"Invalid plan: {plan}")
            
            pricing = self.pricing[plan]
            
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': pricing['currency'],
                        'product_data': {
                            'name': f'SneakerDropBot Premium - {plan.title()}',
                            'description': 'Unlimited sneaker alerts and premium features'
                        },
                        'unit_amount': pricing['amount'],
                        'recurring': {
                            'interval': pricing['interval'],
                            'interval_count': pricing['interval_count']
                        }
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                customer_creation='always',
                metadata={
                    'user_telegram_id': str(user_telegram_id),
                    'plan': plan
                }
            )
            
            return session.url
        
        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise
    
    async def cancel_subscription(self, user_telegram_id: int) -> bool:
        """Cancel user's subscription"""
        try:
            # Get user's Stripe customer ID (you'd need to store this)
            # This is a simplified implementation
            
            # In practice, you'd find the customer by metadata or store customer_id in user record
            customers = stripe.Customer.list(
                limit=1,
                metadata={'user_telegram_id': str(user_telegram_id)}
            )
            
            if not customers.data:
                logger.warning(f"No Stripe customer found for user {user_telegram_id}")
                return False
            
            customer = customers.data[0]
            
            # Get active subscriptions
            subscriptions = stripe.Subscription.list(
                customer=customer.id,
                status='active'
            )
            
            # Cancel all active subscriptions
            for subscription in subscriptions.data:
                stripe.Subscription.delete(subscription.id)
            
            logger.info(f"Cancelled subscription for user {user_telegram_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to cancel subscription for user {user_telegram_id}: {e}")
            return False
    
    def get_pricing_info(self) -> Dict:
        """Get pricing information"""
        return {
            "monthly": {
                "price": self.pricing["monthly"]["amount"] / 100,
                "currency": self.pricing["monthly"]["currency"],
                "interval": "month"
            },
            "yearly": {
                "price": self.pricing["yearly"]["amount"] / 100,
                "currency": self.pricing["yearly"]["currency"],
                "interval": "year",
                "savings": (self.pricing["monthly"]["amount"] * 12 - self.pricing["yearly"]["amount"]) / 100
            }
        }


# Global payment system instance
payment_system = PaymentSystem()
