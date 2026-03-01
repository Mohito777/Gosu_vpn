#!/bin/bash
# SSL initialization script for Docker
# Creates self-signed certs for development or obtains Let's Encrypt certs

set -e

SSL_DIR="./ssl"
CERTBOT_DIR="./ssl"

echo "🔐 SSL Initialization Script"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Create SSL directory
mkdir -p "$SSL_DIR"

# Check if certificates already exist
if [ -f "$SSL_DIR/fullchain.pem" ] && [ -f "$SSL_DIR/privkey.pem" ]; then
    echo "✅ SSL certificates already exist"
    exit 0
fi

# Check if DOMAIN environment variable is set
if [ -z "$DOMAIN" ]; then
    echo "⚠️  DOMAIN environment variable not set"
    echo "📝 Generating self-signed certificate for development..."
    
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/privkey.pem" \
        -out "$SSL_DIR/fullchain.pem" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    
    echo "✅ Self-signed certificate generated"
    echo "⚠️  WARNING: Self-signed cert is for development only!"
    echo "   For production, set DOMAIN env var to get Let's Encrypt cert"
else
    echo "🌐 Domain: $DOMAIN"
    echo "📝 Requesting Let's Encrypt certificate..."
    
    # Create webroot for ACME challenge
    mkdir -p ./ssl/webroot
    
    # First, run certbot in standalone mode to get the cert
    # We need to stop nginx temporarily if it's running
    docker compose stop nginx 2>/dev/null || true
    
    # Run certbot
    docker run --rm \
        -v "$CERTBOT_DIR:/etc/letsencrypt" \
        -v "$PWD/ssl/webroot:/var/www/certbot" \
        certbot/certbot certonly \
        --webroot \
        -w /var/www/certbot \
        -d "$DOMAIN" \
        --email "${CERTBOT_EMAIL:-admin@$DOMAIN}" \
        --agree-tos \
        --no-eff-email \
        --non-interactive
    
    # Copy certificates to SSL directory
    cp "$CERTBOT_DIR/live/$DOMAIN/fullchain.pem" "$SSL_DIR/fullchain.pem"
    cp "$CERTBOT_DIR/live/$DOMAIN/privkey.pem" "$SSL_DIR/privkey.pem"
    cp "$CERTBOT_DIR/live/$DOMAIN/chain.pem" "$SSL_DIR/chain.pem" 2>/dev/null || true
    
    echo "✅ Let's Encrypt certificate obtained"
    
    # Restart nginx
    docker compose start nginx 2>/dev/null || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ SSL initialization complete"
echo ""
echo "Certificate files:"
ls -la "$SSL_DIR"/*.pem 2>/dev/null || echo "No .pem files found"
