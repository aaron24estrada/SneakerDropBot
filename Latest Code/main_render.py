"""
SneakerDropBot - Simplified version for Render.com deployment
This version focuses on core bot functionality without heavy scraping dependencies
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

# Import core components (simplified versions)
from bot.telegram_bot_simple import SimpleTelegramBot
from database.connection_simple import SimpleDatabaseManager
from config.settings_simple import SimpleSettings
from scrapers.lightweight_scraper_manager import LightweightScraperManager


class HealthResponse(BaseModel):
    status: str
    message: str
    timestamp: str


# Global instances
settings = SimpleSettings()
db_manager = SimpleDatabaseManager()
scraper_manager = None
bot = None
monitoring_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    try:
        # Startup
        logger.info("🚀 Starting SneakerDropBot (Render Version)...")
        
        # Initialize database
        await db_manager.connect()
        logger.info("✅ Database connected")
        
        # Initialize scraper manager
        global scraper_manager
        scraper_manager = LightweightScraperManager(db_manager)
        logger.info("✅ Scraper manager initialized")
        
        # Initialize bot
        if settings.telegram_bot_token:
            global bot
            bot = SimpleTelegramBot(settings.telegram_bot_token, scraper_manager, db_manager)
            await bot.initialize()
            logger.info("✅ Telegram bot initialized")
            
            # Start bot polling in background
            asyncio.create_task(bot.start_polling())
            
            # Start monitoring in background (every 15 minutes for free tier)
            global monitoring_task
            monitoring_task = asyncio.create_task(start_monitoring())
            logger.info("✅ Background monitoring started")
        else:
            logger.warning("⚠️ No Telegram bot token provided")
        
        logger.info("🎉 SneakerDropBot is running!")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    finally:
        # Shutdown
        logger.info("🛑 Shutting down SneakerDropBot...")
        
        # Stop monitoring
        if monitoring_task:
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Stop bot
        if bot:
            await bot.stop()
        
        # Close database
        await db_manager.disconnect()
        logger.info("✅ Shutdown complete")


async def start_monitoring():
    """Background monitoring function"""
    while True:
        try:
            logger.info("🔄 Running monitoring cycle...")
            
            if scraper_manager and bot:
                # Generate alerts
                alerts = await scraper_manager.monitor_tracked_sneakers()
                
                # Send alerts via bot
                for alert in alerts:
                    try:
                        await bot.send_alert(alert)
                        await asyncio.sleep(0.5)  # Small delay between alerts
                    except Exception as e:
                        logger.error(f"Failed to send alert: {e}")
                
                if alerts:
                    logger.info(f"✅ Sent {len(alerts)} alerts")
                else:
                    logger.info("ℹ️ No alerts generated")
                
                # Health check
                health = await scraper_manager.get_health_status()
                if health['status'] != 'healthy':
                    logger.warning(f"⚠️ Scraper health: {health['status']}")
            
        except Exception as e:
            logger.error(f"❌ Monitoring cycle error: {e}")
        
        # Wait 15 minutes (900 seconds) for next cycle (optimized for free tier)
        await asyncio.sleep(900)


# Create FastAPI app
app = FastAPI(
    title="SneakerDropBot",
    description="Telegram bot for sneaker drop alerts",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint"""
    from datetime import datetime
    return HealthResponse(
        status="running",
        message="SneakerDropBot is operational",
        timestamp=datetime.utcnow().isoformat()
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    from datetime import datetime
    
    try:
        # Check database connection
        await db_manager.health_check()
        
        # Check bot status
        bot_status = bot.is_running() if bot else False
        
        if bot_status:
            status = "healthy"
            message = "All systems operational"
        else:
            status = "degraded"
            message = "Bot not running"
            
        return HealthResponse(
            status=status,
            message=message,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Telegram webhook endpoint"""
    try:
        if not bot:
            raise HTTPException(status_code=503, detail="Bot not initialized")
        
        update_data = await request.json()
        await bot.process_update(update_data)
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Stripe webhook endpoint"""
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        # Basic webhook handling (implement full logic as needed)
        logger.info("Received Stripe webhook")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Get basic bot statistics"""
    try:
        stats = await db_manager.get_basic_stats()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")


@app.get("/api/scraper/health")
async def get_scraper_health():
    """Get scraper health status"""
    try:
        if not scraper_manager:
            return {"status": "unavailable", "message": "Scraper manager not initialized"}
        
        health = await scraper_manager.get_health_status()
        return {
            "status": "success",
            "data": health
        }
    except Exception as e:
        logger.error(f"Scraper health error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get scraper health")


@app.get("/api/search/{keyword}")
async def search_sneakers_api(keyword: str):
    """Search sneakers via API"""
    try:
        if not scraper_manager:
            raise HTTPException(status_code=503, detail="Scraper not available")
        
        results = await scraper_manager.search_sneakers(keyword, max_results=5)
        return {
            "status": "success",
            "query": keyword,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Search API error: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


@app.post("/api/monitor/force")
async def force_monitoring_cycle():
    """Force a monitoring cycle for testing"""
    try:
        if not scraper_manager or not bot:
            raise HTTPException(status_code=503, detail="System not ready")
        
        logger.info("🔄 Manual monitoring cycle triggered")
        alerts = await scraper_manager.monitor_tracked_sneakers()
        
        # Send alerts
        sent_count = 0
        for alert in alerts:
            try:
                await bot.send_alert(alert)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")
        
        return {
            "status": "success",
            "alerts_generated": len(alerts),
            "alerts_sent": sent_count,
            "message": f"Monitoring cycle complete. {sent_count} alerts sent."
        }
        
    except Exception as e:
        logger.error(f"Manual monitoring error: {e}")
        raise HTTPException(status_code=500, detail="Monitoring failed")


if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main_render:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
