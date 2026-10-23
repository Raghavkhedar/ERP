#!/usr/bin/env bash
# Update the server to the latest production branch.
# Run on the server as the erp user:  sudo -u erp -i /srv/erp/deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

echo "==> Code"
git fetch origin production
# Refuses if someone edited files on the server, instead of losing the edits.
git merge --ff-only origin/production

echo "==> Python packages (no dev tools)"
uv sync --frozen --no-dev

echo "==> CSS"
version=$(sed -n 's/^TAILWIND_VERSION="\(.*\)"/\1/p' scripts/install-tailwind.sh)
bin/tailwindcss --help 2>/dev/null | head -n 1 | grep -q "v$version" || ./scripts/install-tailwind.sh
bin/tailwindcss -i static/css/input.css -o static/css/app.css --minify

echo "==> Checks, static files, migrations"
.venv/bin/python manage.py check --deploy --fail-level WARNING
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py migrate --noinput

echo "==> Restart"
sudo systemctl restart erp
echo "Deployed: $(git log --oneline -1)"
