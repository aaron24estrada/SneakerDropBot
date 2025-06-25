# 🚀 SneakerDropBot Deployment Guide

This guide covers how to deploy SneakerDropBot in various environments, from local development to production.

## 📋 Prerequisites

### Required Services
- **MongoDB** - Database for storing users, products, and alerts
- **Redis** (Optional) - Caching and background task queue
- **Telegram Bot** - Bot token from @BotFather
- **Stripe Account** - For payment processing

### Required API Keys
- Telegram Bot Token
- Stripe Secret/Public/Webhook Keys
- Admin Telegram IDs
- Affiliate IDs (optional)

## 🏠 Local Development Setup

### 1. Quick Start
```bash
# Clone the repository
git clone <repository-url>
cd sneakerdropbot

# Install dependencies
pip install -r requirements.txt

# Create environment file
cp .env.example .env
# Edit .env with your actual configuration

# Run tests
python test_bot.py

# Start the bot
python run.py
```

### 2. Environment Configuration
Edit `.env` file with your actual values:

```env
# Required
TELEGRAM_BOT_TOKEN=123456:ABCdefGHIjklMN-OpqRSTuvwxyz
MONGODB_URI=mongodb://localhost:27017/sneakerdropbot
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLIC_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
ADMIN_TELEGRAM_IDS=123456789

# Optional
STOCKX_AFFILIATE_ID=your_stockx_id
GOAT_AFFILIATE_ID=your_goat_id
```

### 3. Database Setup
```bash
# Start MongoDB locally
mongod --dbpath ./data/db

# Or use MongoDB Atlas (cloud)
# Update MONGODB_URI in .env to your Atlas connection string
```

## 🐳 Docker Deployment

### 1. Using Docker Compose (Recommended)
```bash
# Create .env file with your configuration
cp .env.example .env
# Edit .env with your values

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f sneakerbot

# Stop services
docker-compose down
```

### 2. Manual Docker Deployment
```bash
# Build image
docker build -t sneakerdropbot .

# Run MongoDB
docker run -d --name mongodb \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=password123 \
  mongo:7.0

# Run bot
docker run -d --name sneakerbot \
  --link mongodb:mongodb \
  -p 8000:8000 \
  --env-file .env \
  sneakerdropbot
```

## ☁️ Cloud Deployment

### 1. Heroku Deployment
```bash
# Install Heroku CLI
# Create Heroku app
heroku create your-sneakerbot-app

# Add MongoDB addon
heroku addons:create mongolab:sandbox

# Set environment variables
heroku config:set TELEGRAM_BOT_TOKEN=your_token
heroku config:set STRIPE_SECRET_KEY=sk_test_...
# ... set all required env vars

# Deploy
git push heroku main

# View logs
heroku logs --tail
```

### 2. AWS/DigitalOcean/VPS Deployment
```bash
# On your server
git clone <repository-url>
cd sneakerdropbot

# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Copy and edit environment file
cp .env.example .env
nano .env

# Start services
docker-compose up -d

# Setup SSL (optional)
# Use Let's Encrypt with Certbot
sudo apt install certbot
sudo certbot --nginx -d yourdomain.com
```

### 3. Kubernetes Deployment
```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sneakerbot
spec:
  replicas: 2
  selector:
    matchLabels:
      app: sneakerbot
  template:
    metadata:
      labels:
        app: sneakerbot
    spec:
      containers:
      - name: sneakerbot
        image: your-registry/sneakerdropbot:latest
        ports:
        - containerPort: 8000
        env:
        - name: TELEGRAM_BOT_TOKEN
          valueFrom:
            secretKeyRef:
              name: sneakerbot-secrets
              key: telegram-token
        # Add other env vars from secrets/configmaps
```

## 🔧 Production Configuration

### 1. Environment Variables
```env
# Production settings
DEBUG=False
LOG_LEVEL=INFO

# Database
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/sneakerdropbot

# Security
TELEGRAM_WEBHOOK_URL=https://yourdomain.com/webhooks/telegram

# Performance
SCRAPING_DELAY_MIN=10
SCRAPING_DELAY_MAX=20
```

### 2. Webhook Setup
```bash
# Set Telegram webhook
curl -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://yourdomain.com/webhooks/telegram"

# Set Stripe webhook
# Add webhook endpoint in Stripe Dashboard:
# https://yourdomain.com/webhooks/stripe
# Events: payment_intent.succeeded, payment_intent.payment_failed
```

### 3. SSL/HTTPS Setup
```bash
# Using Let's Encrypt
sudo certbot --nginx -d yourdomain.com

# Or upload your SSL certificates to ./ssl/
# cert.pem and key.pem
```

### 4. Monitoring Setup
```bash
# Add health check monitoring
# Uptime monitoring: https://uptimerobot.com
# Error tracking: https://sentry.io

# Setup log aggregation
# ELK Stack, Datadog, or similar
```

## 📊 Performance Optimization

### 1. Database Optimization
```javascript
// MongoDB indexes (run in mongo shell)
db.users.createIndex({"telegram_id": 1}, {unique: true})
db.products.createIndex({"name": "text", "brand": "text"})
db.tracked_sneakers.createIndex({"user_telegram_id": 1, "is_active": 1})
```

### 2. Caching Setup
```env
# Add Redis for caching
REDIS_URL=redis://localhost:6379/0

# Cache settings
CACHE_TTL=3600
RATE_LIMIT_ENABLED=true
```

### 3. Load Balancing
```nginx
# nginx.conf for multiple instances
upstream sneakerbot_backend {
    server sneakerbot1:8000;
    server sneakerbot2:8000;
    server sneakerbot3:8000;
}

server {
    location / {
        proxy_pass http://sneakerbot_backend;
    }
}
```

## 🔒 Security Best Practices

### 1. Environment Security
```bash
# Use secrets management
# AWS Secrets Manager, HashiCorp Vault, etc.

# Rotate API keys regularly
# Monitor for leaked tokens

# Use non-root user in containers
USER sneakerbot
```

### 2. Network Security
```bash
# Firewall rules
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP
ufw allow 443/tcp  # HTTPS
ufw deny incoming
ufw enable

# Rate limiting in nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
```

### 3. Application Security
```python
# Input validation
# SQL injection prevention
# XSS protection
# CSRF tokens for web interface
```

## 📈 Scaling Considerations

### 1. Horizontal Scaling
- Multiple bot instances
- Load balancer distribution
- Database sharding
- Redis clustering

### 2. Vertical Scaling
- Increase CPU/RAM
- SSD storage
- Dedicated database server
- CDN for static assets

### 3. Microservices Split
- Separate scraping service
- Independent payment service
- Analytics service
- Notification service

## 🔍 Troubleshooting

### Common Issues

#### Bot Not Responding
```bash
# Check logs
docker logs sneakerbot

# Verify token
curl https://api.telegram.org/bot${TOKEN}/getMe

# Check webhooks
curl https://api.telegram.org/bot${TOKEN}/getWebhookInfo
```

#### Database Connection Issues
```bash
# Test MongoDB connection
mongo "mongodb://localhost:27017/sneakerdropbot"

# Check network connectivity
telnet your-mongodb-host 27017
```

#### High Memory Usage
```bash
# Monitor memory usage
docker stats

# Optimize scraping intervals
# Reduce concurrent requests
# Add memory limits in docker-compose
```

#### Rate Limiting Issues
```bash
# Check scraper delays
# Implement exponential backoff
# Use proxy rotation
# Respect robots.txt
```

## 📋 Deployment Checklist

### Pre-deployment
- [ ] All tests passing (`python test_bot.py`)
- [ ] Environment variables configured
- [ ] Database connection tested
- [ ] Stripe webhooks configured
- [ ] SSL certificates ready
- [ ] Domain/DNS configured

### Production Launch
- [ ] Deploy to production environment
- [ ] Set Telegram webhook
- [ ] Configure Stripe webhooks
- [ ] Setup monitoring and alerts
- [ ] Test payment flow
- [ ] Verify scraping functionality
- [ ] Load test the system

### Post-deployment
- [ ] Monitor logs for errors
- [ ] Check system performance
- [ ] Verify user registration flow
- [ ] Test alert delivery
- [ ] Monitor affiliate tracking
- [ ] Setup backup procedures

## 📞 Support

### Getting Help
- **Documentation**: Check README.md and source code comments
- **Logs**: Always check application logs first
- **GitHub Issues**: Report bugs and feature requests
- **Community**: Join our Discord for community support

### Emergency Contacts
- System alerts: Configure PagerDuty/Slack notifications
- Admin access: Ensure multiple admin accounts
- Backup contacts: Document emergency procedures

---

**Happy deployment! 🚀**

*Built with ❤️ by MiniMax Agent*
