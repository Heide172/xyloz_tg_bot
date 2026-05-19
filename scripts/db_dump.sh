#!/usr/bin/env bash
# Дамп исходной БД в custom-формате (pg_dump -Fc).
# Версию pg_dump фиксируем через docker-образ (>= версии сервера).
#
#   SRC_DATABASE_URL=postgresql://user:pass@2.59.43.142:5432/bot ./scripts/db_dump.sh
#
# Результат: ./backups/bot_<ts>.dump  (печатает путь в конце)
set -euo pipefail

: "${SRC_DATABASE_URL:?SRC_DATABASE_URL не задан (postgresql://...)}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"
OUT_DIR="${OUT_DIR:-./backups}"
mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$OUT_DIR/bot_${TS}.dump"

echo "[db_dump] pg_dump ($PG_IMAGE) → $OUT"
docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  pg_dump --dbname="$SRC_DATABASE_URL" -Fc --no-owner --no-privileges \
  > "$OUT"

SZ="$(du -h "$OUT" | cut -f1)"
echo "[db_dump] готово: $OUT ($SZ)"
echo "$OUT"
