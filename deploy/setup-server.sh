#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 droplet for the ERP.
# Safe to run again. Run as root on the server:
#   curl -fsSL https://raw.githubusercontent.com/Raghavkhedar/ERP/production/deploy/setup-server.sh | bash -s erp.example.com
set -euo pipefail

DOMAIN=${1:?usage: setup-server.sh erp.example.com}
REPO=https://github.com/Raghavkhedar/ERP.git
APP=/srv/erp

echo "==> System packages and automatic security updates"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
apt-get install -y git curl ufw unattended-upgrades gnupg
timedatectl set-timezone Asia/Kolkata

echo "==> Firewall: only SSH and web"
ufw allow OpenSSH
ufw allow 80,443/tcp
ufw --force enable

echo "==> Docker (runs PostgreSQL, same as in development)"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

echo "==> Caddy (HTTPS and static files)"
if ! command -v caddy >/dev/null; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key |
    gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

echo "==> App user and code"
id erp >/dev/null 2>&1 || useradd --create-home --shell /bin/bash erp
install -d -o erp -g erp "$APP"
[[ -d "$APP/.git" ]] || sudo -u erp git clone "$REPO" "$APP"
[[ -x ~erp/.local/bin/uv ]] || sudo -u erp -i sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> Secrets (.env, readable only by erp)"
if [[ ! -f "$APP/.env" ]]; then
  cat > "$APP/.env" <<EOF
DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)
DB_PASSWORD=$(openssl rand -hex 16)
ALLOWED_HOSTS=$DOMAIN
EOF
  chown erp:erp "$APP/.env"
  chmod 600 "$APP/.env"
fi

echo "==> Database"
docker compose -f "$APP/compose.yaml" up -d --wait

echo "==> Gunicorn service, Caddy site, backups"
cp "$APP/deploy/erp.service" /etc/systemd/system/erp.service
systemctl daemon-reload
systemctl enable erp
# deploy.sh may restart the app, and nothing else, as root.
echo "erp ALL=(root) NOPASSWD: /usr/bin/systemctl restart erp" > /etc/sudoers.d/erp
chmod 440 /etc/sudoers.d/erp
sed "s/ERP_DOMAIN/$DOMAIN/" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
echo "30 2 * * * root $APP/deploy/backup.sh" > /etc/cron.d/erp-backup

echo "==> First deploy"
sudo -u erp -i "$APP/deploy/deploy.sh"
systemctl reload caddy

echo
echo "Done. Create the first admin account with:"
echo "  sudo -u erp -i sh -c 'cd $APP && .venv/bin/python manage.py createsuperuser'"
echo "Then open https://$DOMAIN/ (HTTPS works once DNS points here)."
