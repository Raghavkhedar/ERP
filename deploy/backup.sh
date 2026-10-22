#!/usr/bin/env bash
# Nightly database dump, keeping the last 14 days. Run by root from cron.
# Restore one with:
#   docker exec -i senken_erp_db pg_restore -U senken_erp -d senken_erp --clean < FILE
set -euo pipefail

DIR=/srv/erp-backups
install -d -m 700 "$DIR"

file="$DIR/senken_erp-$(date +%F).dump"
# Write to a temporary name first, so a failed dump never looks like a good one.
docker exec senken_erp_db pg_dump -U senken_erp -Fc senken_erp > "$file.part"
mv "$file.part" "$file"

find "$DIR" -name '*.dump' -mtime +14 -delete
