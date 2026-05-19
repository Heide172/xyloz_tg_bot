#!/usr/bin/env bash
# Восстановить дамп в целевую (managed Dokploy) БД.
# Целевая БД должна существовать и быть ПУСТОЙ (свежий ресурс Dokploy).
#
#   DST_DATABASE_URL=postgresql://user:pass@<dokploy-db-host>:5432/bot \
#   ./scripts/db_restore.sh ./backups/bot_<ts>.dump
#
set -euo pipefail

DUMP="${1:?Укажи путь к .dump файлу}"
: "${DST_DATABASE_URL:?DST_DATABASE_URL не задан (postgresql://...)}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"

[ -f "$DUMP" ] || { echo "нет файла: $DUMP" >&2; exit 1; }

echo "[db_restore] pg_restore ($PG_IMAGE) ← $DUMP"
# --clean --if-exists: идемпотентно при повторе. --no-owner/-privileges:
# managed-роль отличается от исходной. -j: параллельно.
docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  pg_restore --dbname="$DST_DATABASE_URL" \
  --clean --if-exists --no-owner --no-privileges -j 4 \
  < "$DUMP"

echo "[db_restore] готово. Сверь данные: ./scripts/db_verify.sh \"\$DST_DATABASE_URL\""
