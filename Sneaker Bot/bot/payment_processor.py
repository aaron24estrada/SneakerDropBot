"""
Payment processing for SneakerDropBot using Stripe
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import stripe
from loguru import logger

from database.connection import db_manager
from database.models import UserSubscription, PaymentHistory


class PaymentProcessor:
    """Handle payments and subscriptions via Stripe"""
    
    def __init__(self):
        self.stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        self.stripe_publishable_key = os.getenv("STRIPE_PUBLISHABLE_KEY")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        
        if self.stripe_secret_key:
            stripe.api_key = self.stripe_secret_key
        
        # Pricing
        self.prices = {
            "monthly": {
                "amount": 999,  # $9.99 in cents
                "currency": "usd",
                "interval": "month"
            },
            "yearly": {
                "amount": 9999,  # $99.99 in cents
                "currency": "usd", 
                "interval": "year"
            }
        }
    
    async def create_subscription_payment(self, user_id: int, plan_type: str = "monthly") -> str:
        """Create a Stripe payment link for subscription"""
        try:
            if not self.stripe_secret_key:
                logger.warning("Stripe not configured, returning mock payment URL")
                return f"https://mockpayment.sneakerdropbot.com/subscribe?user_id={user_id}&plan={plan_type}"
            
            price_info = self.prices.get(plan_type, self.prices["monthly"])
            
            # Create or retrieve customer
            customer = await self._get_or_create_customer(user_id)
            
            # Create payment session
            session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                mode='subscription',
                line_items=[{
                    'price_data': {
                        'currency': price_info['currency'],
                        'product_data': {
                            'name': f'SneakerDropBot Premium ({plan_type.title()})',
                            'description': 'Unlimited tracking, instant alerts, flip analysis',
                        },
                        'unit_amount': price_info['amount'],
                        'recurring': {
                            'interval': price_info['interval'],
                        },
                    },
                    'quantity': 1,
                }],
                metadata={
                    'user_id': str(user_id),
                    'plan_type': plan_type
                },
                success_url=f"{os.getenv('WEBHOOK_URL', 'https://api.sneakerdropbot.com')}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{os.getenv('WEBHOOK_URL', 'https://api.sneakerdropbot.com')}/payment/cancel",
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Failed to create subscription payment for user {user_id}: {e}")
            # Return fallback payment URL
            return f"https://fallback.sneakerdropbot.com/subscribe?user_id={user_id}&plan={plan_type}"
    
    async def create_one_time_payment(self, user_id: int, amount: int, description: str) -> str:
        """Create one-time payment link"""
        try:
            if not self.stripe_secret_key:
                return f"https://mockpayment.sneakerdropbot.com/pay?user_id={user_id}&amount={amount}"
            
            customer = await self._get_or_create_customer(user_id)
            
            session = stripe.checkout.Session.create(
                customer=customer.id,
                payment_method_types=['card'],
                mode='payment',
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': 'SneakerDropBot',
                            'description': description,
                        },
                        'unit_amount': amount,
                    },
                    'quantity': 1,
                }],
                metadata={
                    'user_id': str(user_id),
                    'type': 'one_time'
                },
                success_url=f"{os.getenv('WEBHOOK_URL')}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{os.getenv('WEBHOOK_URL')}/payment/cancel",
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Failed to create one-time payment: {e}")
            return f"https://fallback.sneakerdropbot.com/pay?user_id={user_id}&amount={amount}"
    
    async def _get_or_create_customer(self, user_id: int) -> stripe.Customer:
        """Get or create Stripe customer"""
        user = await db_manager.get_user(user_id)
        
        if user and user.stripe_customer_id:
            try:
                customer = stripe.Customer.retrieve(user.stripe_customer_id)
                return customer
            except stripe.error.InvalidRequestError:
                # Customer doesn't exist, create new one
                pass
        
        # Create new customer
        customer_data = {
            'metadata': {'user_id': str(user_id)}
        }
        
        if user and user.username:
            customer_data['email'] = f"{user.username}@telegram.sneakerdropbot.com"
        
        customer = stripe.Customer.create(**customer_data)
        
        # Save customer ID to user
        if user:
            await db_manager.update_user_stripe_customer(user_id, customer.id)
        
        return customer
    
    async def handle_webhook(self, payload: str, sig_header: str) -> bool:
        """Handle Stripe webhook events"""
        try:
            if not self.webhook_secret:
                logger.warning("Webhook secret not configured")
                return False
            
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            
            # Handle different event types
            if event['type'] == 'checkout.session.completed':
                await self._handle_checkout_completed(event['data']['object'])
            elif event['type'] == 'invoice.payment_succeeded':
                await self._handle_payment_succeeded(event['data']['object'])
            elif event['type'] == 'invoice.payment_failed':
                await self._handle_payment_failed(event['data']['object'])
            elif event['type'] == 'customer.subscription.deleted':
                await self._handle_subscription_cancelled(event['data']['object'])
            elif event['type'] == 'customer.subscription.updated':
                await self._handle_subscription_updated(event['data']['object'])
            
            return True
            
        except ValueError as e:
            logger.error(f"Invalid payload in webhook: {e}")
            return False
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature in webhook: {e}")
            return False
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return False
    
    async def _handle_checkout_completed(self, session: Dict):
        """Handle successful checkout"""
        try:
            user_id = int(session['metadata']['user_id'])
            plan_type = session['metadata'].get('plan_type', 'monthly')
            
            # Get subscription details
            subscription_id = session.get('subscription')
            customer_id = session['customer']
            
            if subscription_id:
                # Create subscription record
                subscription = UserSubscription(
                    user_id=user_id,
                    stripe_subscription_id=subscription_id,
                    stripe_customer_id=customer_id,
                    plan_type=plan_type,
                    status="active",
                    current_period_start=datetime.utcnow(),
                    current_period_end=datetime.utcnow() + timedelta(days=30 if plan_type == "monthly" else 365),
                    created_at=datetime.utcnow()
                )
                
                await db_manager.add_subscription(subscription)
                
                # Update user premium status
                await db_manager.update_user_premium_status(user_id, True)
                
                # Log payment
                payment = PaymentHistory(
                    user_id=user_id,
                    stripe_payment_intent=session['payment_intent'],
                    amount=session['amount_total'],
                    currency=session['currency'],
                    status="succeeded",
                    plan_type=plan_type,
                    created_at=datetime.utcnow()
                )
                
                await db_manager.add_payment_history(payment)
                
                logger.info(f"User {user_id} successfully subscribed to {plan_type} plan")
            
        except Exception as e:
            logger.error(f"Error handling checkout completed: {e}")
    
    async def _handle_payment_succeeded(self, invoice: Dict):
        """Handle successful recurring payment"""
        try:
            subscription_id = invoice['subscription']
            
            # Update subscription
            subscription = await db_manager.get_subscription_by_stripe_id(subscription_id)
            if subscription:
                # Extend subscription period
                if subscription.plan_type == "monthly":
                    new_end = subscription.current_period_end + timedelta(days=30)
                else:
                    new_end = subscription.current_period_end + timedelta(days=365)
                
                await db_manager.update_subscription_period(
                    subscription_id, 
                    subscription.current_period_end,
                    new_end
                )
                
                # Log payment
                payment = PaymentHistory(
                    user_id=subscription.user_id,
                    stripe_payment_intent=invoice['payment_intent'],
                    amount=invoice['amount_paid'],
                    currency=invoice['currency'],
                    status="succeeded",
                    plan_type=subscription.plan_type,
                    created_at=datetime.utcnow()
                )
                
                await db_manager.add_payment_history(payment)
                
                logger.info(f"Payment succeeded for subscription {subscription_id}")
            
        except Exception as e:
            logger.error(f"Error handling payment succeeded: {e}")
    
    async def _handle_payment_failed(self, invoice: Dict):
        """Handle failed payment"""
        try:
            subscription_id = invoice['subscription']
            
            subscription = await db_manager.get_subscription_by_stripe_id(subscription_id)
            if subscription:
                # Log failed payment
                payment = PaymentHistory(
                    user_id=subscription.user_id,
                    stripe_payment_intent=invoice.get('payment_intent'),
                    amount=invoice['amount_due'],
                    currency=invoice['currency'],
                    status="failed",
                    plan_type=subscription.plan_type,
                    created_at=datetime.utcnow()
                )
                
                await db_manager.add_payment_history(payment)
                
                # Update subscription status
                await db_manager.update_subscription_status(subscription_id, "past_due")
                
                logger.warning(f"Payment failed for subscription {subscription_id}")
            
        except Exception as e:
            logger.error(f"Error handling payment failed: {e}")
    
    async def _handle_subscription_cancelled(self, subscription: Dict):
        """Handle subscription cancellation"""
        try:
            subscription_id = subscription['id']
            
            # Update subscription status
            await db_manager.update_subscription_status(subscription_id, "cancelled")
            
            # Update user premium status
            sub_record = await db_manager.get_subscription_by_stripe_id(subscription_id)
            if sub_record:
                await db_manager.update_user_premium_status(sub_record.user_id, False)
                logger.info(f"Subscription {subscription_id} cancelled for user {sub_record.user_id}")
            
        except Exception as e:
            logger.error(f"Error handling subscription cancelled: {e}")
    
    async def _handle_subscription_updated(self, subscription: Dict):
        """Handle subscription updates"""
        try:
            subscription_id = subscription['id']
            status = subscription['status']
            
            # Update subscription status
            await db_manager.update_subscription_status(subscription_id, status)
            
            # Update user premium status based on subscription status
            sub_record = await db_manager.get_subscription_by_stripe_id(subscription_id)
            if sub_record:
                is_premium = status in ["active", "trialing"]
                await db_manager.update_user_premium_status(sub_record.user_id, is_premium)
                
                logger.info(f"Subscription {subscription_id} updated to status {status}")
            
        except Exception as e:
            logger.error(f"Error handling subscription updated: {e}")
    
    async def cancel_subscription(self, user_id: int) -> bool:
        """Cancel user's subscription"""
        try:
            subscription = await db_manager.get_active_subscription(user_id)
            
            if not subscription:
                return False
            
            if self.stripe_secret_key:
                # Cancel in Stripe
                stripe.Subscription.delete(subscription.stripe_subscription_id)
            
            # Update in database
            await db_manager.update_subscription_status(
                subscription.stripe_subscription_id, 
                "cancelled"
            )
            await db_manager.update_user_premium_status(user_id, False)
            
            logger.info(f"Cancelled subscription for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling subscription for user {user_id}: {e}")
            return False
    
    async def get_subscription_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user's subscription information"""
        try:
            subscription = await db_manager.get_active_subscription(user_id)
            
            if not subscription:
                return None
            
            info = {
                "plan_type": subscription.plan_type,
                "status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": False
            }
            
            if self.stripe_secret_key and subscription.stripe_subscription_id:
                try:
                    stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
                    info["cancel_at_period_end"] = stripe_sub.cancel_at_period_end
                    info["next_billing_date"] = datetime.fromtimestamp(stripe_sub.current_period_end)
                except:
                    pass
            
            return info
            
        except Exception as e:
            logger.error(f"Error getting subscription info for user {user_id}: {e}")
            return None
    
    async def create_customer_portal_session(self, user_id: int) -> Optional[str]:
        """Create Stripe customer portal session"""
        try:
            if not self.stripe_secret_key:
                return None
            
            user = await db_manager.get_user(user_id)
            if not user or not user.stripe_customer_id:
                return None
            
            session = stripe.billing_portal.Session.create(
                customer=user.stripe_customer_id,
                return_url=f"{os.getenv('WEBHOOK_URL', 'https://t.me/SneakerDropBot')}"
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Error creating customer portal session: {e}")
            return None
    
    async def get_payment_statistics(self) -> Dict[str, Any]:
        """Get payment statistics for admin"""
        try:
            stats = await db_manager.get_payment_statistics()
            
            return {
                "total_subscribers": stats.get("total_subscribers", 0),
                "monthly_subscribers": stats.get("monthly_subscribers", 0),
                "yearly_subscribers": stats.get("yearly_subscribers", 0),
                "monthly_revenue": stats.get("monthly_revenue", 0),
                "yearly_revenue": stats.get("yearly_revenue", 0),
                "total_revenue": stats.get("total_revenue", 0),
                "churn_rate": stats.get("churn_rate", 0),
                "conversion_rate": stats.get("conversion_rate", 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting payment statistics: {e}")
            return {}


# Global payment processor instance
payment_processor = PaymentProcessor()
