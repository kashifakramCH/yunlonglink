#!/usr/bin/env bash
# Run this ONCE after pointing your domain DNS to this server's IP.
# It obtains a Let's Encrypt certificate before starting nginx.
set -euo pipefail

DOMAIN="${1:-api.yunlonglink.com}"
EMAIL="${2:-admin@yunlonglink.com}"

echo "==> Getting TLS certificate for $DOMAIN"

# Start nginx in HTTP-only mode for the ACME challenge
docker compose up -d nginx

docker compose run --rm certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --non-interactive

echo "==> Certificate obtained. Restarting nginx with HTTPS..."
docker compose restart nginx
echo "==> Done. Your API is live at https://$DOMAIN"
