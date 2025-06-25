"""
Simple test script for SneakerDropBot functionality
"""
import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def test_database_connection():
    """Test database connectivity"""
    try:
        from database.connection import init_database, close_database, db_manager
        
        print("🔌 Testing database connection...")
        await init_database()
        
        # Test basic operations
        users_count = await db_manager.db.users.count_documents({})
        print(f"✅ Database connected - {users_count} users in database")
        
        await close_database()
        return True
    
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


async def test_scrapers():
    """Test scraper functionality"""
    try:
        from scrapers.scraper_manager import scraper_manager
        
        print("🕷️  Testing scrapers...")
        
        # Test with a simple search
        products = await scraper_manager.search_all_retailers("Jordan")
        print(f"✅ Scrapers working - Found {len(products)} products for 'Jordan'")
        
        # Test health checks
        health = await scraper_manager.health_check_all_scrapers()
        healthy_count = sum(1 for status in health.values() if status)
        total_count = len(health)
        
        print(f"✅ Scraper health - {healthy_count}/{total_count} scrapers healthy")
        return True
    
    except Exception as e:
        print(f"❌ Scraper test failed: {e}")
        return False


async def test_bot_initialization():
    """Test bot initialization"""
    try:
        from app.bot import bot
        
        print("🤖 Testing bot initialization...")
        await bot.initialize()
        
        print("✅ Bot initialized successfully")
        
        await bot.stop()
        return True
    
    except Exception as e:
        print(f"❌ Bot initialization failed: {e}")
        return False


async def test_monitoring_engine():
    """Test monitoring engine"""
    try:
        from app.monitoring_engine import monitoring_engine
        
        print("⚙️  Testing monitoring engine...")
        
        # Get status
        status = monitoring_engine.get_status()
        print(f"✅ Monitoring engine status: {status}")
        
        return True
    
    except Exception as e:
        print(f"❌ Monitoring engine test failed: {e}")
        return False


async def test_payment_system():
    """Test payment system"""
    try:
        from app.payment_system import payment_system
        
        print("💳 Testing payment system...")
        
        # Test pricing info
        pricing = payment_system.get_pricing_info()
        print(f"✅ Payment system working - Monthly: ${pricing['monthly']['price']}")
        
        return True
    
    except Exception as e:
        print(f"❌ Payment system test failed: {e}")
        return False


async def run_all_tests():
    """Run all tests"""
    print("🧪 Starting SneakerDropBot Tests\n")
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Scrapers", test_scrapers),
        ("Bot Initialization", test_bot_initialization),
        ("Monitoring Engine", test_monitoring_engine),
        ("Payment System", test_payment_system),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"🔍 Running {test_name} test...")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test error: {e}")
            results.append((test_name, False))
        print()
    
    # Summary
    print("📋 Test Results Summary:")
    print("=" * 40)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print("=" * 40)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! SneakerDropBot is ready to run.")
        return True
    else:
        print("⚠️  Some tests failed. Please check the configuration.")
        return False


async def test_quick_functionality():
    """Quick functionality test without full setup"""
    print("⚡ Running quick functionality tests...\n")
    
    # Test utilities
    try:
        # Import utilities without triggering settings loading
        import sys
        import os
        
        # Set dummy environment variables to avoid validation errors
        os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'dummy_token')
        os.environ.setdefault('STRIPE_SECRET_KEY', 'dummy_key')
        os.environ.setdefault('STRIPE_PUBLIC_KEY', 'dummy_key')
        os.environ.setdefault('STRIPE_WEBHOOK_SECRET', 'dummy_secret')
        
        from utils.helpers import format_price, clean_sneaker_name, generate_tracking_id
        
        # Test price formatting
        price_test = format_price(199.99)
        assert price_test == "$199.99", f"Price formatting failed: {price_test}"
        
        # Test sneaker name cleaning
        name_test = clean_sneaker_name("Air Jordan 1 Low Bred - Men's Sneaker")
        assert "Jordan 1 Low Bred" in name_test, f"Name cleaning failed: {name_test}"
        
        # Test tracking ID generation
        tracking_id = generate_tracking_id()
        assert len(tracking_id) == 8, f"Tracking ID length wrong: {tracking_id}"
        
        print("✅ Utility functions working correctly")
        
    except Exception as e:
        print(f"❌ Utility functions test failed: {e}")
        return False
    
    # Test models
    try:
        from database.models import User, TrackedSneaker, SneakerSize, UserTier, AlertType
        
        # Test user model
        user = User(
            telegram_id=123456789,
            username="testuser",
            first_name="Test",
            tier=UserTier.FREE
        )
        assert user.telegram_id == 123456789
        assert not user.is_premium()
        
        # Test sneaker model
        sneaker = TrackedSneaker(
            user_telegram_id=123456789,
            keyword="Jordan 4 Bred",
            sizes=[SneakerSize(us_size=10.5)],
            alert_types=[AlertType.RESTOCK]
        )
        assert sneaker.keyword == "Jordan 4 Bred"
        
        print("✅ Database models working correctly")
        
    except Exception as e:
        print(f"❌ Database models test failed: {e}")
        return False
    
    print("🎉 Quick tests passed! Core functionality is working.")
    return True


if __name__ == "__main__":
    print("👟 SneakerDropBot Test Suite")
    print("=" * 50)
    
    # Check if .env file exists
    if not Path(".env").exists():
        print("⚠️  No .env file found. Running quick tests only...\n")
        
        try:
            success = asyncio.run(test_quick_functionality())
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"❌ Quick test failed: {e}")
            sys.exit(1)
    
    else:
        print("🔧 .env file found. Running full test suite...\n")
        
        try:
            success = asyncio.run(run_all_tests())
            sys.exit(0 if success else 1)
        except KeyboardInterrupt:
            print("\n🛑 Tests interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Test suite failed: {e}")
            sys.exit(1)
