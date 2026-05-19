#!/usr/bin/env bash
# Восстановить дамп в ВЫДЕЛЕННУЮ БД бота на инстансе с чужими данными.
#
#   ВНИМАНИЕ: DST_DATABASE_URL должен указывать на ОТДЕЛЬНУЮ БД
#   (dbname=$BOT_DB_NAME из db_create.sh), НЕ на общую БД с чужими
#   данными. Без --clean: цель должна быть пустой; при повторе —
#   пересоздать БД (drop+create через db_create), не чистить --clean
#   (он мог бы зацепить общий инстанс при ошибочном URL).
#
#   DST_DATABASE_URL=postgresql://user:pass@<host>:5432/xyloz_bot \
#   ./scripts/db_restore.sh ./backups/bot_<ts>.dump
#
set -euo pipefail

DUMP="${1:?Укажи путь к .dump файлу}"
: "${DST_DATABASE_URL:?DST_DATABASE_URL не задан (postgresql://...)}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"

[ -f "$DUMP" ] || { echo "нет файла: $DUMP" >&2; exit 1; }

echo "[db_restore] pg_restore ($PG_IMAGE) ← $DUMP"
echo "[db_restore] цель: $DST_DATABASE_URL — это должна быть ВЫДЕЛЕННАЯ пустая БД"
# Без --clean (цель пустая, выделенная). --no-owner/-privileges:
# managed-роль отличается от исходной. --exit-on-error: не молчать
# при сбоях. -j: параллельно.
docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  pg_restore --dbname="$DST_DATABASE_URL" \
  --no-owner --no-privileges --exit-on-error -j 4 \
  < "$DUMP"

echo "[db_restore] готово. Сверь данные: ./scripts/db_verify.sh \"\$DST_DATABASE_URL\""
