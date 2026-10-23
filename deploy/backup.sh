#!/usr/bin/env bash
# Nightly database dump and uploaded files, keeping the last 14 days.
# Run by root from cron. Restore a dump with:
#   docker exec -i senken_erp_db pg_restore -U senken_erp -d senken_erp --clean < FILE
# and the files with:
#   tar -xzf FILE -C /srv/erp
set -euo pipefail

DIR=/srv/erp-backups
install -d -m 700 "$DIR"

file="$DIR/senken_erp-$(date +%F).dump"
# Write to a temporary name first, so a failed dump never looks like a good one.
docker exec senken_erp_db pg_dump -U senken_erp -Fc senken_erp > "$file.part"
mv "$file.part" "$file"

# Task attachments. Small next to the database, so a full copy each night.
if [[ -d /srv/erp/media ]]; then
  files="$DIR/senken_erp-media-$(date +%F).tar.gz"
  tar -czf "$files.part" -C /srv/erp media
  mv "$files.part" "$files"
fi

find "$DIR" -name '*.dump' -mtime +14 -delete
find "$DIR" -name '*.tar.gz' -mtime +14 -delete
