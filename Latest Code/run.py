#!/usr/bin/env python3
"""
SneakerDropBot - Quick Start Script
Run this to start the complete system locally
"""
import os
import sys
import asyncio
import subprocess
from pathlib import Path
from loguru import logger


class SneakerBotStarter:
    """Helper class to start SneakerDropBot system"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.env_file = self.project_root / ".env"
        
    def check_requirements(self):
        """Check if all requirements are met"""
        logger.info("🔍 Checking requirements...")
        
        # Check Python version
        if sys.version_info < (3, 9):
            logger.error("❌ Python 3.9+ required")
            return False
        
        # Check if .env exists
        if not self.env_file.exists():
            logger.warning("⚠️  .env file not found")
            self.create_env_file()
        
        # Check Docker
        try:
            subprocess.run(["docker", "--version"], check=True, capture_output=True)
            logger.info("✅ Docker found")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("❌ Docker not found. Please install Docker first.")
            return False
        
        # Check Docker Compose
        try:
            subprocess.run(["docker-compose", "--version"], check=True, capture_output=True)
            logger.info("✅ Docker Compose found")
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
                logger.info("✅ Docker Compose (plugin) found")
            except subprocess.CalledProcessError:
                logger.error("❌ Docker Compose not found. Please install Docker Compose.")
                return False
        
        return True
    
    def create_env_file(self):
        """Create .env file from template"""
        logger.info("📝 Creating .env file from template...")
        
        try:
            with open(self.project_root / ".env.example", "r") as template:
                content = template.read()
            
            with open(self.env_file, "w") as env_file:
                env_file.write(content)
            
            logger.info("✅ .env file created")
            logger.warning("⚠️  Please edit .env file with your configuration before continuing")
            
        except Exception as e:
            logger.error(f"❌ Failed to create .env file: {e}")
    
    def check_env_config(self):
        """Check if essential environment variables are configured"""
        logger.info("🔧 Checking environment configuration...")
        
        if not self.env_file.exists():
            logger.error("❌ .env file not found")
            return False
        
        # Read .env file
        env_vars = {}
        with open(self.env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value
        
        # Check essential variables
        essential_vars = [
            "TELEGRAM_BOT_TOKEN",
            "MONGODB_URL",
            "SECRET_KEY"
        ]
        
        missing_vars = []
        for var in essential_vars:
            if var not in env_vars or not env_vars[var] or env_vars[var] in ["your_bot_token_here", "your_very_secure_secret_key_change_this"]:
                missing_vars.append(var)
        
        if missing_vars:
            logger.error(f"❌ Missing or placeholder values for: {', '.join(missing_vars)}")
            logger.info("📝 Please edit .env file with your actual values")
            return False
        
        logger.info("✅ Environment configuration looks good")
        return True
    
    def start_services(self, mode="development"):
        """Start Docker services"""
        logger.info(f"🚀 Starting SneakerDropBot in {mode} mode...")
        
        # Choose docker-compose file based on mode
        compose_files = ["docker-compose.yml"]
        if mode == "development":
            if Path("docker-compose.dev.yml").exists():
                compose_files.append("docker-compose.dev.yml")
        elif mode == "production":
            if Path("docker-compose.prod.yml").exists():
                compose_files.append("docker-compose.prod.yml")
        
        # Build compose command
        compose_cmd = ["docker-compose"]
        for file in compose_files:
            compose_cmd.extend(["-f", file])
        
        try:
            # Start services
            logger.info("📦 Starting Docker services...")
            compose_cmd.extend(["up", "-d", "--build"])
            subprocess.run(compose_cmd, check=True)
            
            logger.info("✅ Services started successfully!")
            logger.info("🔗 Service URLs:")
            logger.info("   • Main API: http://localhost:8000")
            logger.info("   • Health Check: http://localhost:8000/health")
            logger.info("   • API Docs: http://localhost:8000/docs")
            logger.info("   • Grafana: http://localhost:3000")
            logger.info("   • Prometheus: http://localhost:9090")
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to start services: {e}")
            return False
    
    def check_service_health(self):
        """Check if services are healthy"""
        logger.info("🏥 Checking service health...")
        
        import time
        import requests
        
        # Wait for services to start
        logger.info("⏳ Waiting for services to start...")
        time.sleep(30)
        
        # Check main application
        try:
            response = requests.get("http://localhost:8000/health", timeout=10)
            if response.status_code == 200:
                logger.info("✅ Main application is healthy")
            else:
                logger.warning(f"⚠️  Main application returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Main application health check failed: {e}")
        
        # Check if bot is working
        try:
            response = requests.get("http://localhost:8000/stats", timeout=10)
            if response.status_code == 200:
                logger.info("✅ Bot API is responding")
            else:
                logger.warning("⚠️  Bot API may not be fully ready")
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️  Bot API check failed: {e}")
    
    def show_next_steps(self):
        """Show next steps to user"""
        logger.info("🎉 SneakerDropBot is now running!")
        logger.info("")
        logger.info("📋 Next Steps:")
        logger.info("1. Open your Telegram app")
        logger.info("2. Search for your bot (using the bot token you configured)")
        logger.info("3. Send /start to begin using the bot")
        logger.info("4. Configure tracking for your favorite sneakers")
        logger.info("5. Monitor the logs: docker-compose logs -f sneakerdropbot")
        logger.info("")
        logger.info("🔧 Admin Tasks:")
        logger.info("• View logs: docker-compose logs sneakerdropbot")
        logger.info("• Check status: docker-compose ps")
        logger.info("• Stop services: docker-compose down")
        logger.info("• Update: git pull && docker-compose up -d --build")
        logger.info("")
        logger.info("📊 Monitoring:")
        logger.info("• Grafana: http://localhost:3000 (admin/admin)")
        logger.info("• Prometheus: http://localhost:9090")
        logger.info("• API Docs: http://localhost:8000/docs")
        logger.info("")
        logger.info("❓ Need Help?")
        logger.info("• Check README.md for detailed documentation")
        logger.info("• View health status: http://localhost:8000/health")
        logger.info("• Check logs for any errors")
    
    def run_interactive_setup(self):
        """Run interactive setup"""
        logger.info("🤖 SneakerDropBot Interactive Setup")
        logger.info("=" * 50)
        
        # Check requirements
        if not self.check_requirements():
            logger.error("❌ Requirements not met. Please fix issues and try again.")
            return False
        
        # Get bot token if not configured
        if not self.env_file.exists() or not self.check_env_config():
            logger.info("")
            logger.info("🔧 Configuration Required")
            logger.info("You need to configure your bot before starting.")
            logger.info("")
            
            # Ask for bot token
            bot_token = input("Enter your Telegram Bot Token (from @BotFather): ").strip()
            if bot_token:
                self.update_env_var("TELEGRAM_BOT_TOKEN", bot_token)
            
            # Ask for admin ID
            admin_id = input("Enter your Telegram User ID (get from @userinfobot): ").strip()
            if admin_id:
                self.update_env_var("ADMIN_IDS", admin_id)
            
            # Generate secret key
            import secrets
            secret_key = secrets.token_urlsafe(32)
            self.update_env_var("SECRET_KEY", secret_key)
            
            logger.info("✅ Basic configuration updated")
        
        # Ask about mode
        logger.info("")
        mode = input("Choose mode (development/production) [development]: ").strip().lower()
        if not mode:
            mode = "development"
        
        # Start services
        if self.start_services(mode):
            self.check_service_health()
            self.show_next_steps()
            return True
        
        return False
    
    def update_env_var(self, key, value):
        """Update environment variable in .env file"""
        if not self.env_file.exists():
            return
        
        # Read current content
        with open(self.env_file, "r") as f:
            lines = f.readlines()
        
        # Update or add the variable
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                updated = True
                break
        
        if not updated:
            lines.append(f"{key}={value}\n")
        
        # Write back
        with open(self.env_file, "w") as f:
            f.writelines(lines)


def main():
    """Main entry point"""
    # Setup logging
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    starter = SneakerBotStarter()
    
    # Handle command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "check":
            # Just check requirements
            if starter.check_requirements() and starter.check_env_config():
                logger.info("✅ All requirements met!")
            else:
                logger.error("❌ Some requirements not met")
                sys.exit(1)
        
        elif command == "start":
            # Start services directly
            mode = sys.argv[2] if len(sys.argv) > 2 else "development"
            if starter.check_requirements() and starter.check_env_config():
                if starter.start_services(mode):
                    starter.check_service_health()
                    starter.show_next_steps()
                else:
                    sys.exit(1)
            else:
                sys.exit(1)
        
        elif command == "health":
            # Check service health
            starter.check_service_health()
        
        else:
            logger.error(f"Unknown command: {command}")
            logger.info("Available commands: check, start [mode], health")
            sys.exit(1)
    
    else:
        # Run interactive setup
        success = starter.run_interactive_setup()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
