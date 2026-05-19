#!/usr/bin/env bash
# Перенос БД: внешний 2.59.43.142 → managed-БД Dokploy.
# Делает повторяемую часть (дамп→restore→сверка). САМ НЕ переключает
# прод — флип DATABASE_URL и редеплой делает оператор по runbook ниже.
#
# ── RUNBOOK ──────────────────────────────────────────────────────────
# 0. На существующем Postgres-инстансе Dokploy (там УЖЕ есть чужие
#    данные) создать ОТДЕЛЬНУЮ БД под бота — НЕ лить в общую:
#      ADMIN_DATABASE_URL=postgresql://…@<host>:5432/postgres \
#      BOT_DB_NAME=xyloz_bot ./scripts/db_create.sh
#    DST_DATABASE_URL = тот же host, но dbname=xyloz_bot.
#    (db_restore без --clean — цель должна быть этой пустой БД.)
# 1. РЕПЕТИЦИЯ (без даунтайма, в любое время):
#      SRC_DATABASE_URL=<src> DST_DATABASE_URL=<dst> ./scripts/db_migrate.sh
#    Сравнить два блока db_verify: alembic_version, counts, sum(balance)
#    должны совпасть. Это валидирует механику переноса.
#    Повтор (restore без --clean): сначала пересоздать выделенную БД —
#      psql "$ADMIN_DATABASE_URL" -c 'DROP DATABASE "xyloz_bot"'
#      ./scripts/db_create.sh   (DROP только выделенной, не общей!)
# 2. CUTOVER (короткий даунтайм, деньги — без потери транзакций):
#    a. В Dokploy остановить сервисы bot и api (чтобы не было записей).
#    b. Прогнать этот скрипт ещё раз (свежий дамп уже без активных писателей).
#    c. Сверить db_verify источник↔цель (особенно sum(user_balance),
#       economy_tx count, alembic_version).
#    d. Поменять DATABASE_URL в .env (Dokploy env) на DST.
#    e. Редеплой bot и api. Проверить /health и пару действий в Mini App.
#    f. Старую БД НЕ удалять минимум неделю (откат = вернуть DATABASE_URL).
# 3. Настроить cron db_backup.sh на DST (второй пояс бэкапов).
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

: "${SRC_DATABASE_URL:?SRC_DATABASE_URL не задан}"
: "${DST_DATABASE_URL:?DST_DATABASE_URL не задан}"

echo "=== 1/4 dump SRC ==="
DUMP="$(SRC_DATABASE_URL="$SRC_DATABASE_URL" ./scripts/db_dump.sh | tail -n1)"

echo "=== 2/4 verify SRC ==="
./scripts/db_verify.sh "$SRC_DATABASE_URL" | tee /tmp/verify_src.txt

echo "=== 3/4 restore → DST ==="
DST_DATABASE_URL="$DST_DATABASE_URL" ./scripts/db_restore.sh "$DUMP"

echo "=== 4/4 verify DST ==="
./scripts/db_verify.sh "$DST_DATABASE_URL" | tee /tmp/verify_dst.txt

echo
echo "=== DIFF SRC vs DST (пусто = совпало) ==="
diff /tmp/verify_src.txt /tmp/verify_dst.txt && echo "OK: идентично" || \
  echo "!!! РАСХОЖДЕНИЕ — НЕ переключать прод, разбираться"

echo
echo "Данные скопированы. Дальше — шаги CUTOVER из runbook в шапке скрипта."
