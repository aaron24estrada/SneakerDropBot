"""
Enhanced scraper manager with health monitoring and robust error handling
"""
import asyncio
from typing import List, Dict, Optional, Type, Any
from datetime import datetime, timedelta
from loguru import logger

from database.models import SneakerProduct, TrackedSneaker, Retailer, ResellData
from database.connection import db_manager
from scrapers.base_scraper import BaseScraper, MockScraper
from scrapers.enhanced_base_scraper import create_enhanced_scraper
from scrapers.scraper_health_monitor import health_monitor, HealthStatus
from scrapers.nike_scraper import NikeScraper
from scrapers.adidas_scraper import AdidasScraper
from scrapers.stockx_scraper import StockXScraper
from scrapers.goat_scraper import GOATScraper
from scrapers.footlocker_scraper import FootLockerScraper
from scrapers.jdsports_scraper import JDSportsScraper
from scrapers.finishline_scraper import FinishLineScraper


class ScraperManager:
    """Manager for all sneaker scrapers"""
    
    def __init__(self):
        self.scrapers: Dict[Retailer, Type[BaseScraper]] = {
            # Retail Stores (Real implementations)
            Retailer.NIKE: NikeScraper,
            Retailer.ADIDAS: AdidasScraper,
            Retailer.FOOTLOCKER: FootLockerScraper,
            Retailer.FINISH_LINE: FinishLineScraper,
            
            # Resell Platforms (Real implementations)
            Retailer.STOCKX: StockXScraper,
            Retailer.GOAT: GOATScraper,
            
            # Additional retailers (using JDSports scraper as template)
            Retailer.STADIUM_GOODS: lambda: JDSportsScraper(),  # Can be customized
        }
        
        # Resell platforms for market data
        self.resell_scrapers = {
            Retailer.STOCKX: StockXScraper,
            Retailer.GOAT: GOATScraper,
        }
        
        self.last_scrape_times: Dict[Retailer, datetime] = {}
        self.scrape_intervals: Dict[Retailer, int] = {
            # Intervals in minutes
            Retailer.NIKE: 8,        # High priority
            Retailer.ADIDAS: 8,      # High priority
            Retailer.FOOTLOCKER: 12, # Medium priority
            Retailer.FINISH_LINE: 12, # Medium priority
            Retailer.STOCKX: 15,     # Resell data collection
            Retailer.GOAT: 15,       # Resell data collection
            Retailer.STADIUM_GOODS: 20, # Lower priority
        }
        
        # Track API rate limits and health
        self.api_health: Dict[Retailer, bool] = {}
        self.rate_limit_delays: Dict[Retailer, float] = {}
        self.total_requests: Dict[Retailer, int] = {}
        self.successful_requests: Dict[Retailer, int] = {}
    
    async def search_all_retailers(self, keyword: str) -> List[SneakerProduct]:
        """Search all retailers for a keyword"""
        all_products = []
        
        # Create tasks for concurrent scraping
        tasks = []
        
        for retailer, scraper_class in self.scrapers.items():
            task = asyncio.create_task(
                self._search_retailer(retailer, scraper_class, keyword)
            )
            tasks.append(task)
        
        # Execute all searches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_products.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Scraper error: {result}")
        
        logger.info(f"Found {len(all_products)} total products for '{keyword}' across all retailers")
        return all_products
    
    async def _search_retailer(self, retailer: Retailer, scraper_class: Type[BaseScraper], keyword: str) -> List[SneakerProduct]:
        """Search a specific retailer"""
        try:
            async with scraper_class() as scraper:
                products = await scraper.search_products(keyword)
                
                # Store/update products in database
                for product in products:
                    await db_manager.upsert_product(product)
                
                return products
                
        except Exception as e:
            logger.error(f"Failed to search {retailer.value} for '{keyword}': {e}")
            return []
    
    async def monitor_tracked_sneakers(self) -> List[Dict]:
        """Monitor all tracked sneakers for changes"""
        alerts_to_send = []
        
        try:
            # Get all active tracked sneakers grouped by keyword
            tracked_sneakers = await self._get_grouped_tracked_sneakers()
            
            if not tracked_sneakers:
                logger.info("No tracked sneakers to monitor")
                return alerts_to_send
            
            logger.info(f"Monitoring {len(tracked_sneakers)} unique sneaker keywords")
            
            # Monitor each unique keyword
            tasks = []
            for keyword, sneakers in tracked_sneakers.items():
                task = asyncio.create_task(
                    self._monitor_keyword(keyword, sneakers)
                )
                tasks.append(task)
            
            # Execute all monitoring tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    alerts_to_send.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Monitoring error: {result}")
            
            logger.info(f"Generated {len(alerts_to_send)} alerts from monitoring")
            
        except Exception as e:
            logger.error(f"Failed to monitor tracked sneakers: {e}")
        
        return alerts_to_send
    
    async def _get_grouped_tracked_sneakers(self) -> Dict[str, List[TrackedSneaker]]:
        """Get tracked sneakers grouped by keyword"""
        # Get all tracked sneakers from database
        # This is a simplified query - in production you'd paginate large datasets
        cursor = db_manager.db.tracked_sneakers.find({"is_active": True})
        
        grouped = {}
        async for sneaker_data in cursor:
            sneaker = TrackedSneaker(**sneaker_data)
            keyword = sneaker.keyword.lower()
            
            if keyword not in grouped:
                grouped[keyword] = []
            
            grouped[keyword].append(sneaker)
        
        return grouped
    
    async def _monitor_keyword(self, keyword: str, tracked_sneakers: List[TrackedSneaker]) -> List[Dict]:
        """Monitor a specific keyword across all retailers"""
        alerts = []
        
        try:
            # Search for current products
            current_products = await self.search_all_retailers(keyword)
            
            if not current_products:
                logger.debug(f"No products found for keyword: {keyword}")
                return alerts
            
            # Check each tracked sneaker against current products
            for tracked_sneaker in tracked_sneakers:
                sneaker_alerts = await self._check_tracked_sneaker(tracked_sneaker, current_products)
                alerts.extend(sneaker_alerts)
            
        except Exception as e:
            logger.error(f"Failed to monitor keyword '{keyword}': {e}")
        
        return alerts
    
    async def _check_tracked_sneaker(self, tracked_sneaker: TrackedSneaker, current_products: List[SneakerProduct]) -> List[Dict]:
        """Check a tracked sneaker against current products"""
        alerts = []
        
        try:
            # Get user to check alert limits
            user = await db_manager.get_user(tracked_sneaker.user_telegram_id)
            if not user or not user.can_send_alert():
                return alerts
            
            # Find matching products
            matching_products = self._find_matching_products(tracked_sneaker, current_products)
            
            for product in matching_products:
                # Check for restocks
                if tracked_sneaker.alert_types and "restock" in [t.value for t in tracked_sneaker.alert_types]:
                    if await self._is_restock(product):
                        alert = await self._create_restock_alert(tracked_sneaker, product)
                        if alert:
                            alerts.append(alert)
                
                # Check for price drops
                if tracked_sneaker.alert_types and "price_drop" in [t.value for t in tracked_sneaker.alert_types]:
                    if await self._is_price_drop(product):
                        alert = await self._create_price_drop_alert(tracked_sneaker, product)
                        if alert:
                            alerts.append(alert)
                
                # Check for flip opportunities
                if tracked_sneaker.alert_types and "flip_opportunity" in [t.value for t in tracked_sneaker.alert_types]:
                    flip_data = await self._calculate_flip_opportunity(product)
                    if flip_data and flip_data["margin_percentage"] >= 25:  # Minimum 25% margin
                        alert = await self._create_flip_alert(tracked_sneaker, product, flip_data)
                        if alert:
                            alerts.append(alert)
        
        except Exception as e:
            logger.error(f"Failed to check tracked sneaker {tracked_sneaker.id}: {e}")
        
        return alerts
    
    def _find_matching_products(self, tracked_sneaker: TrackedSneaker, products: List[SneakerProduct]) -> List[SneakerProduct]:
        """Find products that match the tracked sneaker criteria"""
        matching = []
        
        keyword_words = tracked_sneaker.keyword.lower().split()
        
        for product in products:
            # Check if product name contains keyword words
            product_name = product.name.lower()
            if all(word in product_name for word in keyword_words):
                
                # Check size availability
                if tracked_sneaker.sizes:
                    size_match = False
                    for tracked_size in tracked_sneaker.sizes:
                        if tracked_size.is_all_sizes:
                            size_match = True
                            break
                        
                        for available_size in product.sizes_available:
                            if tracked_size.us_size == available_size.us_size:
                                size_match = True
                                break
                        
                        if size_match:
                            break
                    
                    if not size_match:
                        continue
                
                # Check price limit
                if tracked_sneaker.max_price and product.price:
                    if product.price > tracked_sneaker.max_price:
                        continue
                
                matching.append(product)
        
        return matching
    
    async def _is_restock(self, product: SneakerProduct) -> bool:
        """Check if product is a restock"""
        if not product.is_in_stock:
            return False
        
        # Get previous product state from database
        previous_product = await db_manager.db.products.find_one({
            "sku": product.sku,
            "retailer": product.retailer,
            "last_checked": {"$lt": datetime.utcnow() - timedelta(minutes=30)}
        })
        
        if previous_product and not previous_product.get("is_in_stock", False):
            return True  # Was out of stock, now in stock = restock
        
        return False
    
    async def _is_price_drop(self, product: SneakerProduct) -> bool:
        """Check if product has a price drop"""
        if not product.price:
            return False
        
        # Get previous price from database
        previous_product = await db_manager.db.products.find_one({
            "sku": product.sku,
            "retailer": product.retailer,
            "price": {"$exists": True, "$ne": None},
            "last_checked": {"$lt": datetime.utcnow() - timedelta(hours=1)}
        })
        
        if previous_product and previous_product.get("price"):
            previous_price = float(previous_product["price"])
            if product.price < previous_price * 0.95:  # 5% or more price drop
                return True
        
        return False
    
    async def _calculate_flip_opportunity(self, product: SneakerProduct) -> Optional[Dict]:
        """Calculate flip opportunity for a product"""
        if not product.price or not product.is_in_stock:
            return None
        
        try:
            # Get recent resell data
            resell_data = await db_manager.get_resell_data(product.name, limit=10)
            
            if not resell_data:
                return None
            
            # Calculate average resell price
            total_price = sum(item.price for item in resell_data)
            avg_resell_price = total_price / len(resell_data)
            
            # Calculate margin
            margin = avg_resell_price - product.price
            margin_percentage = (margin / product.price) * 100
            
            if margin_percentage >= 25:  # Minimum 25% margin
                return {
                    "retail_price": product.price,
                    "avg_resell_price": avg_resell_price,
                    "margin": margin,
                    "margin_percentage": margin_percentage,
                    "sample_size": len(resell_data)
                }
        
        except Exception as e:
            logger.error(f"Failed to calculate flip opportunity for {product.name}: {e}")
        
        return None
    
    async def _create_restock_alert(self, tracked_sneaker: TrackedSneaker, product: SneakerProduct) -> Optional[Dict]:
        """Create a restock alert"""
        try:
            sizes_text = "All sizes" if any(s.is_all_sizes for s in tracked_sneaker.sizes) else ", ".join([str(s.us_size) for s in tracked_sneaker.sizes if s.us_size])
            
            message = f"""
🔁 **Restock Alert!**

👟 **{product.name}** is back on {product.retailer.value.title()}
💰 **Price:** ${product.price:.2f}
👆 **Sizes:** {sizes_text}
🛒 **Buy Now:** {product.url}
            """
            
            return {
                "type": "restock",
                "user_telegram_id": tracked_sneaker.user_telegram_id,
                "tracked_sneaker_id": tracked_sneaker.id,
                "product": product,
                "message": message.strip()
            }
        
        except Exception as e:
            logger.error(f"Failed to create restock alert: {e}")
            return None
    
    async def _create_price_drop_alert(self, tracked_sneaker: TrackedSneaker, product: SneakerProduct) -> Optional[Dict]:
        """Create a price drop alert"""
        try:
            # Get previous price for comparison
            previous_product = await db_manager.db.products.find_one({
                "sku": product.sku,
                "retailer": product.retailer,
                "price": {"$exists": True, "$ne": None}
            }, sort=[("last_checked", -1)])
            
            previous_price = previous_product.get("price", product.price) if previous_product else product.price
            savings = previous_price - product.price
            
            message = f"""
💸 **Price Drop Alert!**

👟 **{product.name}** on {product.retailer.value.title()}
💰 **Now:** ${product.price:.2f} (was ${previous_price:.2f})
💵 **Save:** ${savings:.2f}
🛒 **Buy Now:** {product.url}
            """
            
            return {
                "type": "price_drop",
                "user_telegram_id": tracked_sneaker.user_telegram_id,
                "tracked_sneaker_id": tracked_sneaker.id,
                "product": product,
                "message": message.strip(),
                "savings": savings
            }
        
        except Exception as e:
            logger.error(f"Failed to create price drop alert: {e}")
            return None
    
    async def _create_flip_alert(self, tracked_sneaker: TrackedSneaker, product: SneakerProduct, flip_data: Dict) -> Optional[Dict]:
        """Create a flip opportunity alert"""
        try:
            message = f"""
📈 **Flip Opportunity!**

👟 **{product.name}** on {product.retailer.value.title()}
💰 **Buy for:** ${flip_data['retail_price']:.2f}
📊 **Resell avg:** ${flip_data['avg_resell_price']:.2f}
💵 **Profit:** ${flip_data['margin']:.2f} (+{flip_data['margin_percentage']:.1f}%)
🛒 **Buy Now:** {product.url}

*Based on {flip_data['sample_size']} recent sales*
            """
            
            return {
                "type": "flip_opportunity",
                "user_telegram_id": tracked_sneaker.user_telegram_id,
                "tracked_sneaker_id": tracked_sneaker.id,
                "product": product,
                "message": message.strip(),
                "flip_data": flip_data
            }
        
        except Exception as e:
            logger.error(f"Failed to create flip alert: {e}")
            return None
    
    async def collect_resell_data(self, sneaker_keywords: List[str]) -> List[ResellData]:
        """Collect resell market data for tracked sneakers"""
        all_resell_data = []
        
        try:
            logger.info(f"Collecting resell data for {len(sneaker_keywords)} keywords")
            
            # Create tasks for concurrent data collection
            tasks = []
            
            for keyword in sneaker_keywords:
                for retailer, scraper_class in self.resell_scrapers.items():
                    task = asyncio.create_task(
                        self._collect_resell_data_for_keyword(retailer, scraper_class, keyword)
                    )
                    tasks.append(task)
            
            # Execute all collection tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_resell_data.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Resell data collection error: {result}")
            
            # Store collected data in database
            for resell_item in all_resell_data:
                await db_manager.add_resell_data(resell_item)
            
            logger.info(f"Collected {len(all_resell_data)} resell data points")
            
        except Exception as e:
            logger.error(f"Failed to collect resell data: {e}")
        
        return all_resell_data
    
    async def _collect_resell_data_for_keyword(self, retailer: Retailer, scraper_class: Type[BaseScraper], keyword: str) -> List[ResellData]:
        """Collect resell data for a specific keyword from a retailer"""
        resell_data = []
        
        try:
            async with scraper_class() as scraper:
                # Search for products
                products = await scraper.search_products(keyword)
                
                # For each product, try to get market data
                for product in products[:3]:  # Limit to top 3 products per keyword
                    if hasattr(scraper, 'get_market_data'):
                        try:
                            market_data = await scraper.get_market_data(product.url)
                            resell_data.extend(market_data)
                        except Exception as e:
                            logger.warning(f"Failed to get market data for {product.url}: {e}")
                
        except Exception as e:
            logger.error(f"Failed to collect resell data from {retailer.value} for '{keyword}': {e}")
        
        return resell_data
    
    async def get_comprehensive_market_data(self, sneaker_name: str) -> Dict[str, Any]:
        """Get comprehensive market data for a specific sneaker"""
        market_data = {
            "sneaker_name": sneaker_name,
            "retail_availability": [],
            "resell_data": [],
            "price_analysis": {},
            "trend_analysis": {}
        }
        
        try:
            # Search retail stores
            retail_tasks = []
            for retailer, scraper_class in self.scrapers.items():
                if retailer not in self.resell_scrapers:  # Exclude resell platforms
                    task = asyncio.create_task(
                        self._search_retailer(retailer, scraper_class, sneaker_name)
                    )
                    retail_tasks.append(task)
            
            retail_results = await asyncio.gather(*retail_tasks, return_exceptions=True)
            
            for result in retail_results:
                if isinstance(result, list):
                    market_data["retail_availability"].extend(result)
            
            # Get resell data
            resell_data = await db_manager.get_resell_data(sneaker_name, limit=20)
            market_data["resell_data"] = [item.dict() for item in resell_data]
            
            # Calculate price analysis
            if resell_data:
                prices = [item.price for item in resell_data]
                market_data["price_analysis"] = {
                    "average_resell_price": sum(prices) / len(prices),
                    "lowest_resell_price": min(prices),
                    "highest_resell_price": max(prices),
                    "sample_size": len(prices)
                }
                
                # Get retail prices for comparison
                retail_prices = [p.price for p in market_data["retail_availability"] if p.price]
                if retail_prices:
                    avg_retail = sum(retail_prices) / len(retail_prices)
                    avg_resell = market_data["price_analysis"]["average_resell_price"]
                    
                    market_data["price_analysis"]["retail_vs_resell"] = {
                        "average_retail_price": avg_retail,
                        "price_premium": avg_resell - avg_retail,
                        "premium_percentage": ((avg_resell - avg_retail) / avg_retail) * 100 if avg_retail > 0 else 0
                    }
            
        except Exception as e:
            logger.error(f"Failed to get comprehensive market data for '{sneaker_name}': {e}")
        
        return market_data
    
    async def health_check_all_scrapers(self) -> Dict[str, bool]:
        """Check health of all scrapers"""
        health_status = {}
        
        tasks = []
        for retailer, scraper_class in self.scrapers.items():
            task = asyncio.create_task(
                self._check_scraper_health(retailer, scraper_class)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            retailer = list(self.scrapers.keys())[i]
            if isinstance(result, bool):
                health_status[retailer.value] = result
                self.api_health[retailer] = result
            else:
                health_status[retailer.value] = False
                self.api_health[retailer] = False
                logger.error(f"Health check failed for {retailer.value}: {result}")
        
        return health_status
    
    async def _check_scraper_health(self, retailer: Retailer, scraper_class: Type[BaseScraper]) -> bool:
        """Check health of a specific scraper"""
        try:
            # Track request
            self.total_requests[retailer] = self.total_requests.get(retailer, 0) + 1
            
            async with scraper_class() as scraper:
                health = await scraper.health_check()
                
                if health:
                    self.successful_requests[retailer] = self.successful_requests.get(retailer, 0) + 1
                
                return health
        except Exception as e:
            logger.error(f"Health check failed for {retailer.value}: {e}")
            return False
    
    def get_scraper_analytics(self) -> Dict[str, Any]:
        """Get analytics for all scrapers"""
        analytics = {
            "total_scrapers": len(self.scrapers),
            "healthy_scrapers": sum(1 for health in self.api_health.values() if health),
            "scrapers_status": {},
            "performance_metrics": {},
            "rate_limits": {}
        }
        
        for retailer in self.scrapers.keys():
            retailer_name = retailer.value
            
            # Health status
            analytics["scrapers_status"][retailer_name] = {
                "healthy": self.api_health.get(retailer, False),
                "last_check": datetime.utcnow().isoformat(),
                "scrape_interval": self.scrape_intervals.get(retailer, 0)
            }
            
            # Performance metrics
            total_reqs = self.total_requests.get(retailer, 0)
            successful_reqs = self.successful_requests.get(retailer, 0)
            
            analytics["performance_metrics"][retailer_name] = {
                "total_requests": total_reqs,
                "successful_requests": successful_reqs,
                "success_rate": (successful_reqs / total_reqs * 100) if total_reqs > 0 else 0,
                "error_rate": ((total_reqs - successful_reqs) / total_reqs * 100) if total_reqs > 0 else 0
            }
            
            # Rate limit info
            analytics["rate_limits"][retailer_name] = {
                "current_delay": self.rate_limit_delays.get(retailer, 0),
                "has_rate_limit": self.rate_limit_delays.get(retailer, 0) > 0
            }
        
        return analytics
    
    async def optimize_scraping_intervals(self):
        """Optimize scraping intervals based on success rates"""
        try:
            for retailer in self.scrapers.keys():
                total_reqs = self.total_requests.get(retailer, 0)
                successful_reqs = self.successful_requests.get(retailer, 0)
                
                if total_reqs > 10:  # Only optimize after sufficient data
                    success_rate = successful_reqs / total_reqs
                    current_interval = self.scrape_intervals[retailer]
                    
                    if success_rate < 0.7:  # Less than 70% success rate
                        # Increase interval to reduce load
                        new_interval = min(current_interval * 1.5, 60)  # Max 60 minutes
                        self.scrape_intervals[retailer] = int(new_interval)
                        logger.info(f"Increased scraping interval for {retailer.value} to {new_interval} minutes")
                    
                    elif success_rate > 0.95:  # Greater than 95% success rate
                        # Decrease interval for faster updates
                        new_interval = max(current_interval * 0.8, 5)  # Min 5 minutes
                        self.scrape_intervals[retailer] = int(new_interval)
                        logger.info(f"Decreased scraping interval for {retailer.value} to {new_interval} minutes")
        
        except Exception as e:
            logger.error(f"Failed to optimize scraping intervals: {e}")
    
    async def get_trending_sneakers(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get trending sneakers based on tracking and market activity"""
        trending = []
        
        try:
            # Get most tracked sneakers
            pipeline = [
                {"$match": {"is_active": True}},
                {"$group": {
                    "_id": "$keyword",
                    "count": {"$sum": 1},
                    "latest_tracking": {"$max": "$created_at"}
                }},
                {"$sort": {"count": -1}},
                {"$limit": 20}
            ]
            
            cursor = db_manager.db.tracked_sneakers.aggregate(pipeline)
            
            async for item in cursor:
                keyword = item["_id"]
                tracking_count = item["count"]
                
                # Get market data for trending analysis
                market_data = await self.get_comprehensive_market_data(keyword)
                
                trending_item = {
                    "sneaker_name": keyword,
                    "tracking_count": tracking_count,
                    "retail_availability_count": len(market_data["retail_availability"]),
                    "resell_data_points": len(market_data["resell_data"]),
                    "price_analysis": market_data.get("price_analysis", {}),
                    "trend_score": self._calculate_trend_score(tracking_count, market_data)
                }
                
                trending.append(trending_item)
            
            # Sort by trend score
            trending.sort(key=lambda x: x["trend_score"], reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to get trending sneakers: {e}")
        
        return trending[:10]  # Top 10
    
    def _calculate_trend_score(self, tracking_count: int, market_data: Dict) -> float:
        """Calculate trend score based on various factors"""
        score = 0
        
        # Base score from tracking count
        score += tracking_count * 10
        
        # Bonus for retail availability
        score += len(market_data.get("retail_availability", [])) * 5
        
        # Bonus for resell activity
        score += len(market_data.get("resell_data", [])) * 3
        
        # Bonus for high price premium (indicates hype)
        price_analysis = market_data.get("price_analysis", {})
        if "retail_vs_resell" in price_analysis:
            premium_pct = price_analysis["retail_vs_resell"].get("premium_percentage", 0)
            if premium_pct > 50:  # More than 50% premium
                score += premium_pct * 2
        
        return score
    
    # === ENHANCED HEALTH MONITORING METHODS ===
    
    async def check_all_scrapers_health(self) -> Dict[str, Any]:
        """Check health of all scrapers with detailed monitoring"""
        try:
            health_results = await health_monitor.check_scraper_health(self)
            return {
                "status": "success",
                "health_summary": await health_monitor.get_health_summary(),
                "detailed_metrics": {retailer: health_results.get(retailer) for retailer in health_results},
                "suggestions": await self._get_health_suggestions(health_results)
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _get_health_suggestions(self, health_results: Dict) -> Dict[str, List[str]]:
        """Get health improvement suggestions for each retailer"""
        suggestions = {}
        for retailer, metrics in health_results.items():
            if metrics and metrics.status != HealthStatus.HEALTHY:
                suggestions[retailer] = await health_monitor.suggest_fixes(retailer)
        return suggestions
    
    async def get_enhanced_scraper_instance(self, retailer: Retailer) -> BaseScraper:
        """Get enhanced scraper instance with health monitoring"""
        try:
            # Try to get enhanced scraper first
            enhanced_scraper = create_enhanced_scraper(retailer)
            if enhanced_scraper:
                return enhanced_scraper
        except Exception as e:
            logger.warning(f"Failed to create enhanced scraper for {retailer.value}: {e}")
        
        # Fallback to original scraper
        scraper_class = self.scrapers.get(retailer)
        if scraper_class:
            if callable(scraper_class):
                return scraper_class()
            return scraper_class
        
        logger.warning(f"No scraper available for {retailer.value}, using mock scraper")
        return MockScraper(retailer)
    
    async def search_with_fallback(self, keyword: str, preferred_retailers: List[Retailer] = None) -> List[SneakerProduct]:
        """Search with intelligent fallback based on health status"""
        all_products = []
        
        # Get health status
        health_results = await health_monitor.check_scraper_health(self)
        
        # Determine which retailers to use
        retailers_to_use = preferred_retailers or list(self.scrapers.keys())
        
        # Sort by health status (healthy first)
        retailers_to_use.sort(key=lambda r: self._get_retailer_priority(r, health_results))
        
        # Execute searches with intelligent batching
        healthy_tasks = []
        backup_tasks = []
        
        for retailer in retailers_to_use:
            retailer_health = health_results.get(retailer.value)
            
            if retailer_health and retailer_health.status == HealthStatus.HEALTHY:
                task = asyncio.create_task(self._search_with_monitoring(retailer, keyword))
                healthy_tasks.append(task)
            elif retailer_health and retailer_health.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]:
                # Add to backup with delay
                task = asyncio.create_task(
                    self._search_with_delay(retailer, keyword, delay=2.0)
                )
                backup_tasks.append(task)
        
        # Execute healthy scrapers first
        if healthy_tasks:
            healthy_results = await asyncio.gather(*healthy_tasks, return_exceptions=True)
            for result in healthy_results:
                if isinstance(result, list):
                    all_products.extend(result)
        
        # If we don't have enough results, try backup scrapers
        if len(all_products) < 5 and backup_tasks:
            logger.info("Running backup scrapers due to insufficient results")
            backup_results = await asyncio.gather(*backup_tasks, return_exceptions=True)
            for result in backup_results:
                if isinstance(result, list):
                    all_products.extend(result)
        
        logger.info(f"Enhanced search for '{keyword}' found {len(all_products)} products")
        return all_products
    
    def _get_retailer_priority(self, retailer: Retailer, health_results: Dict) -> int:
        """Get priority score for retailer (lower = higher priority)"""
        health = health_results.get(retailer.value)
        if not health:
            return 100  # Unknown health = low priority
        
        priority_map = {
            HealthStatus.HEALTHY: 1,
            HealthStatus.WARNING: 2, 
            HealthStatus.CRITICAL: 3,
            HealthStatus.DOWN: 4
        }
        
        return priority_map.get(health.status, 100)
    
    async def _search_with_monitoring(self, retailer: Retailer, keyword: str) -> List[SneakerProduct]:
        """Search with health monitoring"""
        start_time = datetime.now()
        try:
            scraper = await self.get_enhanced_scraper_instance(retailer)
            async with scraper:
                products = await scraper.search_products(keyword)
                
                # Update health metrics
                self._update_scraper_metrics(retailer, True, start_time)
                
                # Store products
                for product in products:
                    await db_manager.upsert_product(product)
                
                return products
                
        except Exception as e:
            self._update_scraper_metrics(retailer, False, start_time, str(e))
            logger.error(f"Enhanced search failed for {retailer.value}: {e}")
            return []
    
    async def _search_with_delay(self, retailer: Retailer, keyword: str, delay: float) -> List[SneakerProduct]:
        """Search with delay (for unhealthy scrapers)"""
        await asyncio.sleep(delay)
        return await self._search_with_monitoring(retailer, keyword)
    
    def _update_scraper_metrics(self, retailer: Retailer, success: bool, start_time: datetime, error: str = None):
        """Update scraper performance metrics"""
        try:
            response_time = (datetime.now() - start_time).total_seconds()
            
            # Update counters
            if retailer not in self.total_requests:
                self.total_requests[retailer] = 0
            if retailer not in self.successful_requests:
                self.successful_requests[retailer] = 0
            
            self.total_requests[retailer] += 1
            if success:
                self.successful_requests[retailer] += 1
            
            # Store metrics for health monitoring
            asyncio.create_task(self._store_performance_metrics(retailer, success, response_time, error))
            
        except Exception as e:
            logger.error(f"Failed to update metrics for {retailer.value}: {e}")
    
    async def _store_performance_metrics(self, retailer: Retailer, success: bool, response_time: float, error: str = None):
        """Store performance metrics in database"""
        try:
            await db_manager.store_scraper_metrics({
                "retailer": retailer.value,
                "timestamp": datetime.now(),
                "success": success,
                "response_time": response_time,
                "error": error
            })
        except Exception as e:
            logger.debug(f"Failed to store performance metrics: {e}")
    
    async def auto_heal_scrapers(self) -> Dict[str, str]:
        """Automatically attempt to heal failing scrapers"""
        healing_results = {}
        
        try:
            health_results = await health_monitor.check_scraper_health(self)
            
            for retailer, metrics in health_results.items():
                if not metrics or metrics.status in [HealthStatus.CRITICAL, HealthStatus.DOWN]:
                    healing_result = await self._attempt_scraper_healing(retailer, metrics)
                    healing_results[retailer] = healing_result
            
        except Exception as e:
            logger.error(f"Auto-healing failed: {e}")
            healing_results["error"] = str(e)
        
        return healing_results
    
    async def _attempt_scraper_healing(self, retailer: str, metrics) -> str:
        """Attempt to heal a specific scraper"""
        try:
            retailer_enum = Retailer(retailer)
            
            # Reset circuit breaker if it's been long enough
            scraper = await self.get_enhanced_scraper_instance(retailer_enum)
            if hasattr(scraper, 'failure_count'):
                scraper.failure_count = 0
                scraper.last_failure_time = None
            
            # Test with a simple search
            test_result = await self._search_with_monitoring(retailer_enum, "test")
            
            if test_result is not None:  # Even empty list is success
                return "healed"
            else:
                return "healing_failed"
                
        except Exception as e:
            logger.error(f"Healing attempt failed for {retailer}: {e}")
            return f"healing_error: {str(e)}"
    
    async def get_performance_analytics(self, hours: int = 24) -> Dict[str, Any]:
        """Get detailed performance analytics"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            analytics = {
                "summary": {
                    "total_retailers": len(self.scrapers),
                    "healthy_retailers": 0,
                    "unhealthy_retailers": 0,
                    "average_success_rate": 0.0,
                    "total_requests": sum(self.total_requests.values()),
                    "total_successful": sum(self.successful_requests.values())
                },
                "by_retailer": {},
                "trending_issues": await health_monitor.get_trending_issues(hours),
                "health_summary": await health_monitor.get_health_summary()
            }
            
            # Calculate per-retailer analytics
            for retailer, total in self.total_requests.items():
                successful = self.successful_requests.get(retailer, 0)
                success_rate = successful / total if total > 0 else 0.0
                
                analytics["by_retailer"][retailer.value] = {
                    "success_rate": success_rate,
                    "total_requests": total,
                    "successful_requests": successful,
                    "last_activity": self.last_scrape_times.get(retailer)
                }
                
                if success_rate > 0.7:
                    analytics["summary"]["healthy_retailers"] += 1
                else:
                    analytics["summary"]["unhealthy_retailers"] += 1
            
            # Calculate overall success rate
            total_all = analytics["summary"]["total_requests"]
            successful_all = analytics["summary"]["total_successful"]
            analytics["summary"]["average_success_rate"] = successful_all / total_all if total_all > 0 else 0.0
            
            return analytics
            
        except Exception as e:
            logger.error(f"Failed to get performance analytics: {e}")
            return {"error": str(e)}


# Global scraper manager instance
scraper_manager = ScraperManager()
