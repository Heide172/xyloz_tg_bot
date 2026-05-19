#!/usr/bin/env bash
# Создать ВЫДЕЛЕННУЮ БД под бота на инстансе, где уже есть чужие
# данные. Подключаемся к maintenance-БД (обычно 'postgres') и делаем
# только CREATE DATABASE — чужие БД не трогаются.
#
#   ADMIN_DATABASE_URL=postgresql://user:pass@<host>:5432/postgres \
#   BOT_DB_NAME=xyloz_bot ./scripts/db_create.sh
#
# Дальше DST_DATABASE_URL = тот же host, но dbname=$BOT_DB_NAME.
set -euo pipefail

: "${ADMIN_DATABASE_URL:?ADMIN_DATABASE_URL не задан (…/postgres — maintenance db)}"
BOT_DB_NAME="${BOT_DB_NAME:-xyloz_bot}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"

# Имя БД — только латиница/цифры/подчёркивание (защита от инъекции в DDL).
if ! [[ "$BOT_DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "недопустимое BOT_DB_NAME: $BOT_DB_NAME" >&2
  exit 1
fi

echo "[db_create] CREATE DATABASE $BOT_DB_NAME (если нет)"
docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${BOT_DB_NAME}'" | grep -q 1 \
  && echo "[db_create] уже существует — ок" \
  || docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
       psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c \
       "CREATE DATABASE \"${BOT_DB_NAME}\""

echo "[db_create] готово. DST_DATABASE_URL = тот же хост, dbname=${BOT_DB_NAME}"
