#!/bin/bash
# Startup script for VPN Bot Docker deployment
# Handles SSL initialization, database setup, and service startup

set -e

echo "🚀 VPN Bot Startup Script"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Load environment variables
if [ -f .env ]; then
    echo "📄 Loading .env..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# Initialize SSL
echo "🔐 Checking SSL certificates..."
bash init-ssl.sh

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p logs ssl

# Set permissions
chmod 600 ssl/*.pem 2>/dev/null || true

# Initialize database (if running locally)
if [ "$SKIP_DB_INIT" != "true" ]; then
    echo "🗄️  Database will be initialized by the bot"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Pre-start checks complete"
echo ""
echo "🔄 Starting Docker services..."
docker compose up -d

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ VPN Bot started successfully!"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f bot     # View bot logs"
echo "  docker compose logs -f nginx   # View nginx logs"
echo "  docker compose down            # Stop all services"
echo ""
