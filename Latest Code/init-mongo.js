// MongoDB initialization script for SneakerDropBot
// This script runs when the container is first created

// Switch to the sneakerdropbot database
db = db.getSiblingDB('sneakerdropbot');

// Create collections with initial indexes
db.createCollection('users');
db.createCollection('tracked_sneakers');
db.createCollection('products');
db.createCollection('alerts');
db.createCollection('resell_data');
db.createCollection('payments');
db.createCollection('analytics');

// Create indexes for better performance
print('Creating database indexes...');

// Users collection indexes
db.users.createIndex({ "telegram_id": 1 }, { unique: true });
db.users.createIndex({ "tier": 1 });
db.users.createIndex({ "subscription_expires_at": 1 });
db.users.createIndex({ "created_at": 1 });

// Tracked sneakers collection indexes
db.tracked_sneakers.createIndex({ 
    "user_telegram_id": 1, 
    "keyword": 1, 
    "is_active": 1 
});
db.tracked_sneakers.createIndex({ "keyword": "text" });
db.tracked_sneakers.createIndex({ "created_at": 1 });

// Products collection indexes
db.products.createIndex({ 
    "name": "text", 
    "brand": "text", 
    "model": "text", 
    "colorway": "text" 
});
db.products.createIndex({ "sku": 1, "retailer": 1 }, { unique: true });
db.products.createIndex({ "retailer": 1 });
db.products.createIndex({ "last_checked": 1 });
db.products.createIndex({ "is_in_stock": 1 });
db.products.createIndex({ "price": 1 });

// Alerts collection indexes
db.alerts.createIndex({ "user_telegram_id": 1 });
db.alerts.createIndex({ "sent_at": 1 });
db.alerts.createIndex({ "alert_type": 1 });
db.alerts.createIndex({ "tracked_sneaker_id": 1 });

// Resell data collection indexes
db.resell_data.createIndex({ 
    "sneaker_name": 1, 
    "platform": 1, 
    "created_at": -1 
});
db.resell_data.createIndex({ "last_sale_date": 1 });
db.resell_data.createIndex({ "price": 1 });

// Payments collection indexes
db.payments.createIndex({ "user_telegram_id": 1 });
db.payments.createIndex({ "stripe_payment_intent_id": 1 }, { unique: true });
db.payments.createIndex({ "status": 1 });
db.payments.createIndex({ "created_at": 1 });

// Analytics collection indexes
db.analytics.createIndex({ "date": 1 }, { unique: true });

print('Database initialization completed successfully!');

// Insert sample data for testing (optional)
print('Inserting sample data...');

// Sample admin user (replace with actual admin telegram ID)
// db.users.insertOne({
//     telegram_id: 123456789,
//     username: "admin",
//     first_name: "Admin",
//     tier: "premium",
//     subscription_expires_at: null,
//     is_active: true,
//     created_at: new Date(),
//     updated_at: new Date(),
//     last_interaction: new Date(),
//     alerts_sent_this_month: 0,
//     alerts_reset_date: new Date(),
//     tracked_sneakers: []
// });

// Sample analytics entry
db.analytics.insertOne({
    date: new Date(new Date().setHours(0, 0, 0, 0)),
    total_users: 0,
    premium_users: 0,
    alerts_sent: 0,
    new_signups: 0,
    affiliate_clicks: 0,
    revenue: 0.0
});

print('Sample data inserted successfully!');
print('SneakerDropBot database is ready! 👟');
