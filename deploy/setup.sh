#!/usr/bin/env bash
# One-time server setup on Ubuntu 22.04/24.04: installs Docker, opens the firewall,
# writes deploy/.env with random secrets, and starts everything.
#
#   git clone https://github.com/yshemashree/Campaign-Manager-Predixion-AI-.git
#   cd Campaign-Manager-Predixion-AI-
#   ./deploy/setup.sh admin@yourmail.com
set -euo pipefail

ADMIN_EMAIL=${1:?usage: ./deploy/setup.sh <superadmin email>}
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

# Oracle's Ubuntu images block ports 80/443 with iptables even after the cloud firewall allows them.
if sudo iptables -L INPUT -n | grep -q "REJECT"; then
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo sh -c 'command -v netfilter-persistent >/dev/null && netfilter-persistent save || true'
fi

if [ ! -f deploy/.env ]; then
  IP=$(curl -fsS https://api.ipify.org)
  ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')
  cat > deploy/.env <<ENV
SITE_ADDRESS=${IP//./-}.sslip.io
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -base64 32)
WEBHOOK_SIGNING_SECRET=$(openssl rand -hex 32)
SEED_SUPERADMIN_EMAIL=$ADMIN_EMAIL
SEED_SUPERADMIN_PASSWORD=$ADMIN_PASSWORD
MOCK_SPEED=10
ENV
  echo "Superadmin: $ADMIN_EMAIL / $ADMIN_PASSWORD  (also saved in deploy/.env)"
fi

sudo docker compose --env-file deploy/.env -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build --wait
echo "Live at https://$(grep ^SITE_ADDRESS deploy/.env | cut -d= -f2)"
