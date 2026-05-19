#!/usr/bin/env bash
# Сводка по БД для сверки источник↔цель ПЕРЕД переключением.
# Запусти на обеих и сравни вывод построчно.
#
#   ./scripts/db_verify.sh "postgresql://user:pass@host:5432/bot"
#
set -euo pipefail

URL="${1:?Укажи DATABASE_URL}"
PG_IMAGE="${PG_IMAGE:-postgres:16}"

SQL=$(cat <<'EOSQL'
SELECT 'alembic_version' AS k, (SELECT version_num FROM alembic_version) AS v
UNION ALL SELECT 'users',            count(*)::text FROM users
UNION ALL SELECT 'user_balance',     count(*)::text FROM user_balance
UNION ALL SELECT 'sum(user_balance)',COALESCE(sum(balance),0)::text FROM user_balance
UNION ALL SELECT 'chat_bank',        count(*)::text FROM chat_bank
UNION ALL SELECT 'sum(chat_bank)',   COALESCE(sum(balance),0)::text FROM chat_bank
UNION ALL SELECT 'economy_tx',       count(*)::text FROM economy_tx
UNION ALL SELECT 'messages',         count(*)::text FROM messages
UNION ALL SELECT 'clicker_farms',    count(*)::text FROM clicker_farms
UNION ALL SELECT 'gacha_collection', count(*)::text FROM gacha_collection
UNION ALL SELECT 'markets',          count(*)::text FROM markets
UNION ALL SELECT 'bets',             count(*)::text FROM bets
UNION ALL SELECT 'feedback',         count(*)::text FROM feedback;
EOSQL
)

echo "[db_verify] $URL"
docker run --rm -i -e PGCONNECT_TIMEOUT=15 "$PG_IMAGE" \
  psql "$URL" -v ON_ERROR_STOP=1 -A -F' | ' -t -c "$SQL"
