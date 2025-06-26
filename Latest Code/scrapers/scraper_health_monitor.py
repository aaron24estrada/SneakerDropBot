"""
Scraper health monitoring and alerting system
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from loguru import logger

from database.connection import db_manager
from database.models import Retailer
from config.settings import settings


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DOWN = "down"


@dataclass
class ScraperHealthMetrics:
    """Health metrics for a scraper"""
    retailer: str
    status: HealthStatus
    success_rate: float
    total_requests: int
    successful_requests: int
    consecutive_failures: int
    last_successful_scrape: Optional[datetime]
    circuit_breaker_open: bool
    method_success_rates: Dict[str, float]
    error_patterns: List[str]
    response_time_avg: float
    last_checked: datetime
    issues: List[str]


@dataclass
class HealthAlert:
    """Health alert data"""
    retailer: str
    alert_type: str
    severity: HealthStatus
    message: str
    timestamp: datetime
    details: Dict[str, Any]


class ScraperHealthMonitor:
    """Monitor scraper health and send alerts"""
    
    def __init__(self):
        self.health_metrics: Dict[str, ScraperHealthMetrics] = {}
        self.alert_history: List[HealthAlert] = []
        self.alert_cooldown = 300  # 5 minutes between same alerts
        self.last_alerts: Dict[str, datetime] = {}
        
        # Health thresholds
        self.thresholds = {
            "success_rate_warning": 0.7,      # Below 70% success rate
            "success_rate_critical": 0.5,     # Below 50% success rate
            "consecutive_failures_warning": 5, # 5 consecutive failures
            "consecutive_failures_critical": 10, # 10 consecutive failures
            "stale_data_hours": 2,             # No successful scrape in 2 hours
            "response_time_warning": 5.0,      # Average response time > 5s
            "response_time_critical": 10.0,    # Average response time > 10s
        }
    
    async def check_scraper_health(self, scraper_manager) -> Dict[str, ScraperHealthMetrics]:
        """Check health of all scrapers"""
        health_results = {}
        
        for retailer, scraper in scraper_manager.scrapers.items():
            try:
                health_data = await scraper.health_check()
                metrics = await self._analyze_health_data(retailer.value, health_data)
                health_results[retailer.value] = metrics
                
                # Store metrics for trending
                await self._store_health_metrics(metrics)
                
                # Check for alerts
                await self._check_for_alerts(metrics)
                
            except Exception as e:
                logger.error(f"Health check failed for {retailer.value}: {e}")
                metrics = ScraperHealthMetrics(
                    retailer=retailer.value,
                    status=HealthStatus.DOWN,
                    success_rate=0.0,
                    total_requests=0,
                    successful_requests=0,
                    consecutive_failures=999,
                    last_successful_scrape=None,
                    circuit_breaker_open=True,
                    method_success_rates={},
                    error_patterns=[str(e)],
                    response_time_avg=0.0,
                    last_checked=datetime.now(),
                    issues=[f"Health check failed: {e}"]
                )
                health_results[retailer.value] = metrics
        
        self.health_metrics = health_results
        return health_results
    
    async def _analyze_health_data(self, retailer: str, health_data: Dict) -> ScraperHealthMetrics:
        """Analyze raw health data and determine status"""
        issues = []
        
        # Extract basic metrics
        success_rate = health_data.get("success_rate", 0.0)
        total_requests = health_data.get("total_requests", 0)
        successful_requests = health_data.get("successful_requests", 0)
        consecutive_failures = health_data.get("consecutive_failures", 0)
        last_successful_scrape = health_data.get("last_successful_scrape")
        circuit_breaker_open = health_data.get("circuit_breaker_open", False)
        method_success_rates = health_data.get("method_success_rates", {})
        
        # Calculate response time (would come from actual monitoring)
        response_time_avg = health_data.get("response_time_avg", 0.0)
        
        # Determine overall status
        status = HealthStatus.HEALTHY
        
        # Check connectivity
        if not health_data.get("connectivity", False):
            status = HealthStatus.DOWN
            issues.append("No connectivity")
        
        # Check circuit breaker
        elif circuit_breaker_open:
            status = HealthStatus.CRITICAL
            issues.append("Circuit breaker is open")
        
        # Check success rate
        elif success_rate < self.thresholds["success_rate_critical"]:
            status = HealthStatus.CRITICAL
            issues.append(f"Success rate critically low: {success_rate:.1%}")
        elif success_rate < self.thresholds["success_rate_warning"]:
            if status == HealthStatus.HEALTHY:
                status = HealthStatus.WARNING
            issues.append(f"Success rate low: {success_rate:.1%}")
        
        # Check consecutive failures
        if consecutive_failures >= self.thresholds["consecutive_failures_critical"]:
            status = HealthStatus.CRITICAL
            issues.append(f"Too many consecutive failures: {consecutive_failures}")
        elif consecutive_failures >= self.thresholds["consecutive_failures_warning"]:
            if status in [HealthStatus.HEALTHY, HealthStatus.WARNING]:
                status = HealthStatus.WARNING
            issues.append(f"Multiple consecutive failures: {consecutive_failures}")
        
        # Check stale data
        if last_successful_scrape:
            hours_since_success = (datetime.now() - last_successful_scrape).total_seconds() / 3600
            if hours_since_success > self.thresholds["stale_data_hours"]:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.WARNING
                issues.append(f"No successful scrape in {hours_since_success:.1f} hours")
        elif total_requests > 0:
            status = HealthStatus.CRITICAL
            issues.append("No successful scrapes recorded")
        
        # Check response times
        if response_time_avg > self.thresholds["response_time_critical"]:
            if status in [HealthStatus.HEALTHY, HealthStatus.WARNING]:
                status = HealthStatus.WARNING
            issues.append(f"Response time very slow: {response_time_avg:.1f}s")
        elif response_time_avg > self.thresholds["response_time_warning"]:
            if status == HealthStatus.HEALTHY:
                status = HealthStatus.WARNING
            issues.append(f"Response time slow: {response_time_avg:.1f}s")
        
        # Extract error patterns
        error_patterns = self._extract_error_patterns(health_data.get("recent_errors", []))
        
        return ScraperHealthMetrics(
            retailer=retailer,
            status=status,
            success_rate=success_rate,
            total_requests=total_requests,
            successful_requests=successful_requests,
            consecutive_failures=consecutive_failures,
            last_successful_scrape=last_successful_scrape,
            circuit_breaker_open=circuit_breaker_open,
            method_success_rates=method_success_rates,
            error_patterns=error_patterns,
            response_time_avg=response_time_avg,
            last_checked=datetime.now(),
            issues=issues
        )
    
    def _extract_error_patterns(self, recent_errors: List[str]) -> List[str]:
        """Extract common error patterns from recent errors"""
        if not recent_errors:
            return []
        
        # Common error patterns to look for
        patterns = {
            "rate_limiting": ["429", "rate limit", "too many requests"],
            "blocking": ["403", "forbidden", "blocked", "captcha"],
            "site_changes": ["not found", "404", "element not found", "selector"],
            "network": ["timeout", "connection", "network", "dns"],
            "parsing": ["json", "parse", "decode", "invalid"]
        }
        
        found_patterns = []
        for pattern_name, keywords in patterns.items():
            for error in recent_errors:
                error_lower = error.lower()
                if any(keyword in error_lower for keyword in keywords):
                    found_patterns.append(pattern_name)
                    break
        
        return list(set(found_patterns))  # Remove duplicates
    
    async def _store_health_metrics(self, metrics: ScraperHealthMetrics):
        """Store health metrics in database for trending"""
        try:
            await db_manager.store_health_metrics({
                "retailer": metrics.retailer,
                "timestamp": metrics.last_checked,
                "status": metrics.status.value,
                "success_rate": metrics.success_rate,
                "total_requests": metrics.total_requests,
                "consecutive_failures": metrics.consecutive_failures,
                "response_time_avg": metrics.response_time_avg,
                "issues": metrics.issues
            })
        except Exception as e:
            logger.error(f"Failed to store health metrics for {metrics.retailer}: {e}")
    
    async def _check_for_alerts(self, metrics: ScraperHealthMetrics):
        """Check if alerts should be sent for this scraper"""
        retailer = metrics.retailer
        now = datetime.now()
        
        # Check cooldown
        last_alert = self.last_alerts.get(retailer)
        if last_alert and (now - last_alert).total_seconds() < self.alert_cooldown:
            return
        
        alerts_to_send = []
        
        # Status change alerts
        if metrics.status in [HealthStatus.CRITICAL, HealthStatus.DOWN]:
            alerts_to_send.append(HealthAlert(
                retailer=retailer,
                alert_type="status_critical",
                severity=metrics.status,
                message=f"Scraper for {retailer} is {metrics.status.value}",
                timestamp=now,
                details={
                    "success_rate": metrics.success_rate,
                    "consecutive_failures": metrics.consecutive_failures,
                    "issues": metrics.issues
                }
            ))
        
        # Pattern-specific alerts
        if "site_changes" in metrics.error_patterns:
            alerts_to_send.append(HealthAlert(
                retailer=retailer,
                alert_type="site_changes",
                severity=HealthStatus.WARNING,
                message=f"Possible site changes detected for {retailer}",
                timestamp=now,
                details={
                    "error_patterns": metrics.error_patterns,
                    "method_success_rates": metrics.method_success_rates
                }
            ))
        
        if "rate_limiting" in metrics.error_patterns:
            alerts_to_send.append(HealthAlert(
                retailer=retailer,
                alert_type="rate_limiting",
                severity=HealthStatus.WARNING,
                message=f"Rate limiting detected for {retailer}",
                timestamp=now,
                details={"error_patterns": metrics.error_patterns}
            ))
        
        # Send alerts
        for alert in alerts_to_send:
            await self._send_alert(alert)
            self.last_alerts[retailer] = now
    
    async def _send_alert(self, alert: HealthAlert):
        """Send health alert"""
        try:
            # Store alert in database
            await db_manager.store_health_alert(asdict(alert))
            
            # Add to history
            self.alert_history.append(alert)
            
            # Keep only recent alerts in memory
            cutoff = datetime.now() - timedelta(hours=24)
            self.alert_history = [a for a in self.alert_history if a.timestamp > cutoff]
            
            # Send notification (if configured)
            await self._send_alert_notification(alert)
            
            logger.warning(f"Health alert sent: {alert.message}")
            
        except Exception as e:
            logger.error(f"Failed to send health alert: {e}")
    
    async def _send_alert_notification(self, alert: HealthAlert):
        """Send alert notification to configured channels"""
        try:
            # Send to admin Telegram if configured
            if hasattr(settings, 'admin_telegram_chat_id') and settings.admin_telegram_chat_id:
                from bot.telegram_bot import bot
                if bot:
                    message = self._format_alert_message(alert)
                    await bot.application.bot.send_message(
                        chat_id=settings.admin_telegram_chat_id,
                        text=message,
                        parse_mode='Markdown'
                    )
            
            # Could add other notification channels here (email, Slack, etc.)
            
        except Exception as e:
            logger.error(f"Failed to send alert notification: {e}")
    
    def _format_alert_message(self, alert: HealthAlert) -> str:
        """Format alert for Telegram"""
        emoji = {
            HealthStatus.WARNING: "⚠️",
            HealthStatus.CRITICAL: "🚨",
            HealthStatus.DOWN: "💀"
        }
        
        message = f"{emoji.get(alert.severity, '❗')} **Scraper Alert**\n\n"
        message += f"**Retailer:** {alert.retailer}\n"
        message += f"**Type:** {alert.alert_type}\n"
        message += f"**Severity:** {alert.severity.value}\n"
        message += f"**Message:** {alert.message}\n"
        message += f"**Time:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if alert.details:
            message += "\n**Details:**\n"
            for key, value in alert.details.items():
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                elif isinstance(value, dict):
                    value = json.dumps(value, indent=2)
                message += f"• **{key}:** {value}\n"
        
        return message
    
    async def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary"""
        if not self.health_metrics:
            return {"status": "no_data", "message": "No health data available"}
        
        total_scrapers = len(self.health_metrics)
        healthy = sum(1 for m in self.health_metrics.values() if m.status == HealthStatus.HEALTHY)
        warning = sum(1 for m in self.health_metrics.values() if m.status == HealthStatus.WARNING)
        critical = sum(1 for m in self.health_metrics.values() if m.status == HealthStatus.CRITICAL)
        down = sum(1 for m in self.health_metrics.values() if m.status == HealthStatus.DOWN)
        
        overall_status = HealthStatus.HEALTHY
        if down > 0 or critical > total_scrapers / 2:
            overall_status = HealthStatus.CRITICAL
        elif critical > 0 or warning > total_scrapers / 2:
            overall_status = HealthStatus.WARNING
        
        avg_success_rate = sum(m.success_rate for m in self.health_metrics.values()) / total_scrapers
        
        return {
            "overall_status": overall_status.value,
            "total_scrapers": total_scrapers,
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "down": down,
            "average_success_rate": avg_success_rate,
            "last_checked": max(m.last_checked for m in self.health_metrics.values()),
            "recent_alerts": len([a for a in self.alert_history if a.timestamp > datetime.now() - timedelta(hours=1)])
        }
    
    async def get_retailer_health(self, retailer: str) -> Optional[ScraperHealthMetrics]:
        """Get health metrics for specific retailer"""
        return self.health_metrics.get(retailer)
    
    async def get_trending_issues(self, hours: int = 24) -> Dict[str, int]:
        """Get trending issues over the specified time period"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_alerts = [a for a in self.alert_history if a.timestamp > cutoff]
        
        issue_counts = {}
        for alert in recent_alerts:
            alert_type = alert.alert_type
            issue_counts[alert_type] = issue_counts.get(alert_type, 0) + 1
        
        return dict(sorted(issue_counts.items(), key=lambda x: x[1], reverse=True))
    
    async def suggest_fixes(self, retailer: str) -> List[str]:
        """Suggest fixes based on health metrics"""
        metrics = self.health_metrics.get(retailer)
        if not metrics:
            return ["No health data available"]
        
        suggestions = []
        
        if "site_changes" in metrics.error_patterns:
            suggestions.append("🔧 Site layout may have changed - check selectors and parsing logic")
            suggestions.append("🔍 Review recent errors and update HTML/JSON parsing patterns")
            suggestions.append("🛠️ Consider adding more fallback parsing methods")
        
        if "rate_limiting" in metrics.error_patterns:
            suggestions.append("⏱️ Implement longer delays between requests")
            suggestions.append("🔄 Add proxy rotation to distribute requests")
            suggestions.append("📉 Reduce scraping frequency temporarily")
        
        if "blocking" in metrics.error_patterns:
            suggestions.append("🎭 Rotate User-Agent strings more frequently")
            suggestions.append("🌐 Use residential proxies or VPN")
            suggestions.append("🕐 Implement random request timing")
        
        if metrics.circuit_breaker_open:
            suggestions.append("⚡ Circuit breaker is open - wait for cooldown or manual reset")
            suggestions.append("🔄 Review and fix underlying issues before retrying")
        
        if metrics.consecutive_failures > 5:
            suggestions.append("🚨 Multiple failures detected - check network connectivity")
            suggestions.append("🔧 Review scraper configuration and endpoints")
        
        if not suggestions:
            suggestions.append("✅ No specific issues detected - monitor for trends")
        
        return suggestions


# Global health monitor instance
health_monitor = ScraperHealthMonitor()
