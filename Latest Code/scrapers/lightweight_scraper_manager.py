"""
Lightweight scraper manager for Render.com deployment
Focuses on essential scraping without heavy dependencies
"""
import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from loguru import logger

from database.connection_simple import SimpleDatabaseManager
from scrapers.lightweight_scrapers import (
    LightweightNikeScraper,
    LightweightStockXScraper,
    LightweightAdidasScraper,
    MockScraper
)


class LightweightScraperManager:
    """Lightweight scraper manager for Render deployment"""
    
    def __init__(self, db_manager: SimpleDatabaseManager):
        self.db_manager = db_manager
        
        # Initialize lightweight scrapers
        self.scrapers = {
            "nike": LightweightNikeScraper(),
            "adidas": LightweightAdidasScraper(),
            "stockx": LightweightStockXScraper(),
            # Use mock scrapers for less critical retailers to save resources
            "footlocker": MockScraper("footlocker"),
            "finishline": MockScraper("finishline")
        }
        
        # Track scraper health
        self.last_successful_scrape = {}
        self.scraper_errors = {}
        self.is_monitoring = False
    
    async def search_sneakers(self, keyword: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search for sneakers across available scrapers"""
        all_results = []
        
        try:
            # Create tasks for concurrent scraping (limited for free tier)
            tasks = []
            for retailer_name, scraper in list(self.scrapers.items())[:3]:  # Limit to 3 scrapers
                task = asyncio.create_task(
                    self._search_retailer_safe(retailer_name, scraper, keyword)
                )
                tasks.append(task)
            
            # Execute searches with timeout
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0  # 30 second timeout for all searches
            )
            
            for result in results:
                if isinstance(result, list):
                    all_results.extend(result)
                elif isinstance(result, Exception):
                    logger.warning(f"Scraper error: {result}")
            
            # Limit results and add metadata
            limited_results = all_results[:max_results]
            for result in limited_results:
                result['scraped_at'] = datetime.utcnow().isoformat()
                result['source'] = 'SneakerDropBot'
            
            logger.info(f"Found {len(limited_results)} results for '{keyword}'")
            return limited_results
            
        except asyncio.TimeoutError:
            logger.warning("Search timeout - returning partial results")
            return all_results[:max_results]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    async def _search_retailer_safe(self, retailer: str, scraper, keyword: str) -> List[Dict[str, Any]]:
        """Safely search a retailer with error handling"""
        try:
            results = await scraper.search_products(keyword)
            self.last_successful_scrape[retailer] = datetime.utcnow()
            
            # Reset error count on success
            if retailer in self.scraper_errors:
                self.scraper_errors[retailer] = 0
            
            return results
            
        except Exception as e:
            logger.warning(f"Failed to search {retailer}: {e}")
            
            # Track errors
            if retailer not in self.scraper_errors:
                self.scraper_errors[retailer] = 0
            self.scraper_errors[retailer] += 1
            
            return []
    
    async def monitor_tracked_sneakers(self) -> List[Dict[str, Any]]:
        """Monitor tracked sneakers and generate alerts"""
        alerts = []
        
        try:
            # Get all tracked sneakers from database
            tracked_sneakers = await self._get_all_tracked_sneakers()
            
            if not tracked_sneakers:
                logger.info("No sneakers being tracked")
                return alerts
            
            logger.info(f"Monitoring {len(tracked_sneakers)} tracked sneakers")
            
            # Group by sneaker name to avoid duplicate searches
            grouped_sneakers = {}
            for sneaker in tracked_sneakers:
                name = sneaker.get('sneaker_name', '').lower()
                if name not in grouped_sneakers:
                    grouped_sneakers[name] = []
                grouped_sneakers[name].append(sneaker)
            
            # Monitor each unique sneaker
            for sneaker_name, tracking_list in grouped_sneakers.items():
                try:
                    sneaker_alerts = await self._monitor_sneaker(sneaker_name, tracking_list)
                    alerts.extend(sneaker_alerts)
                    
                    # Small delay between sneakers to be respectful
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Failed to monitor {sneaker_name}: {e}")
                    continue
            
            logger.info(f"Generated {len(alerts)} alerts")
            return alerts
            
        except Exception as e:
            logger.error(f"Monitoring failed: {e}")
            return alerts
    
    async def _get_all_tracked_sneakers(self) -> List[Dict[str, Any]]:
        """Get all tracked sneakers from database"""
        try:
            cursor = self.db_manager.db.tracked_sneakers.find({"is_active": True})
            tracked = []
            async for item in cursor:
                tracked.append(item)
            return tracked
        except Exception as e:
            logger.error(f"Failed to get tracked sneakers: {e}")
            return []
    
    async def _monitor_sneaker(self, sneaker_name: str, tracking_list: List[Dict]) -> List[Dict[str, Any]]:
        """Monitor a specific sneaker for alerts"""
        alerts = []
        
        try:
            # Search for the sneaker
            search_results = await self.search_sneakers(sneaker_name, max_results=3)
            
            if not search_results:
                return alerts
            
            # Check each tracking request against results
            for tracking in tracking_list:
                user_id = tracking.get('user_id')
                target_size = tracking.get('size')
                price_limit = tracking.get('price_limit')
                
                for result in search_results:
                    alert = await self._check_for_alert(
                        user_id, tracking, result, target_size, price_limit
                    )
                    if alert:
                        alerts.append(alert)
            
            return alerts
            
        except Exception as e:
            logger.error(f"Failed to monitor sneaker {sneaker_name}: {e}")
            return alerts
    
    async def _check_for_alert(self, user_id: int, tracking: Dict, result: Dict, 
                              target_size: str, price_limit: Optional[float]) -> Optional[Dict[str, Any]]:
        """Check if a result should trigger an alert"""
        try:
            # Basic availability check
            if not result.get('in_stock', False):
                return None
            
            # Price limit check
            price = result.get('price')
            if price_limit and price and price > price_limit:
                return None
            
            # Size check (simplified)
            available_sizes = result.get('sizes', [])
            if target_size and target_size.lower() != 'all':
                # Simple size matching (could be enhanced)
                size_available = any(
                    str(target_size) in str(size) for size in available_sizes
                ) if available_sizes else True  # Assume available if no size info
                
                if not size_available:
                    return None
            
            # Check if we've already sent this alert recently
            if await self._was_recent_alert(user_id, result.get('name', ''), result.get('retailer', '')):
                return None
            
            # Create alert
            alert = {
                'user_id': user_id,
                'sneaker_name': result.get('name'),
                'retailer': result.get('retailer'),
                'price': price,
                'url': result.get('url'),
                'image': result.get('image'),
                'alert_type': 'restock',
                'message': self._generate_alert_message(result),
                'created_at': datetime.utcnow()
            }
            
            # Log the alert
            await self.db_manager.log_alert(alert)
            
            return alert
            
        except Exception as e:
            logger.error(f"Alert check failed: {e}")
            return None
    
    async def _was_recent_alert(self, user_id: int, sneaker_name: str, retailer: str) -> bool:
        """Check if we sent a similar alert recently"""
        try:
            cutoff = datetime.utcnow() - timedelta(hours=2)  # 2 hour cooldown
            
            recent_alert = await self.db_manager.db.alerts.find_one({
                'user_id': user_id,
                'sneaker_name': sneaker_name,
                'retailer': retailer,
                'created_at': {'$gte': cutoff}
            })
            
            return recent_alert is not None
            
        except Exception as e:
            logger.error(f"Recent alert check failed: {e}")
            return False
    
    def _generate_alert_message(self, result: Dict[str, Any]) -> str:
        """Generate alert message from result"""
        name = result.get('name', 'Sneaker')
        retailer = result.get('retailer', 'Store')
        price = result.get('price')
        
        if price:
            return f"🔥 {name} is back in stock at {retailer} for ${price}!"
        else:
            return f"🔥 {name} is back in stock at {retailer}!"
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get scraper health status"""
        health = {
            'status': 'healthy',
            'scrapers': {},
            'last_check': datetime.utcnow().isoformat(),
            'total_scrapers': len(self.scrapers),
            'healthy_scrapers': 0,
            'error_scrapers': 0
        }
        
        for retailer in self.scrapers.keys():
            last_success = self.last_successful_scrape.get(retailer)
            error_count = self.scraper_errors.get(retailer, 0)
            
            if error_count > 5:
                status = 'critical'
                health['error_scrapers'] += 1
            elif error_count > 2:
                status = 'warning'
            elif last_success and (datetime.utcnow() - last_success) < timedelta(hours=1):
                status = 'healthy'
                health['healthy_scrapers'] += 1
            else:
                status = 'unknown'
            
            health['scrapers'][retailer] = {
                'status': status,
                'last_success': last_success.isoformat() if last_success else None,
                'error_count': error_count
            }
        
        # Determine overall status
        if health['error_scrapers'] > health['healthy_scrapers']:
            health['status'] = 'degraded'
        elif health['error_scrapers'] > 0:
            health['status'] = 'warning'
        
        return health
    
    async def start_monitoring(self, interval_minutes: int = 10):
        """Start background monitoring"""
        if self.is_monitoring:
            logger.warning("Monitoring already started")
            return
        
        self.is_monitoring = True
        logger.info(f"Starting monitoring with {interval_minutes} minute intervals")
        
        try:
            while self.is_monitoring:
                try:
                    alerts = await self.monitor_tracked_sneakers()
                    
                    if alerts:
                        logger.info(f"Generated {len(alerts)} alerts")
                        # Alerts will be sent by the telegram bot
                    
                except Exception as e:
                    logger.error(f"Monitoring cycle failed: {e}")
                
                # Wait for next cycle
                await asyncio.sleep(interval_minutes * 60)
                
        except asyncio.CancelledError:
            logger.info("Monitoring cancelled")
        finally:
            self.is_monitoring = False
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self.is_monitoring = False
        logger.info("Monitoring stopped")
