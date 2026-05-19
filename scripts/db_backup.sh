#!/usr/bin/env bash
# Регулярный бэкап (cron на Dokploy-хосте). Managed-БД Dokploy может
# иметь свои бэкапы — это второй пояс безопасности под наши деньги.
#
#   crontab:  0 */6 * * *  DATABASE_URL=... /path/scripts/db_backup.sh
#
# Хранит последние BACKUP_KEEP файлов, остальное удаляет.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL не задан}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"
DIR="${BACKUP_DIR:-./backups}"
KEEP="${BACKUP_KEEP:-28}"
mkdir -p "$DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$DIR/auto_${TS}.dump"

docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  pg_dump --dbname="$DATABASE_URL" -Fc --no-owner --no-privileges \
  > "$OUT"

echo "[db_backup] $OUT ($(du -h "$OUT" | cut -f1))"

# Ротация: оставить KEEP свежих auto_*.dump.
ls -1t "$DIR"/auto_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r f; do
  rm -f "$f" && echo "[db_backup] удалён старый: $f"
done
