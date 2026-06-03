# vpndigest — мониторинг VPN-чатов + дайджесты

Встроено в инфраструктуру `xyloz_tg_bot`: общий `Base`/`SessionLocal` (`common.db`),
логгер (`common.logger`), LLM через `bot.services.ai_client` (OpenCode). Своих
зависимостей не добавляет — `pyrogram`, `tgcrypto`, `APScheduler`, `openai` уже в
`requirements.txt`.

Userbot читает VPN-чаты от имени **отдельного аккаунта** (read-only), копит сообщения
в таблицы `vpn_*` (отдельно от основной аналитики бота) и раз в сутки шлёт **дайджест**
(гибрид: TL;DR + секции по чатам/темам) тем же аккаунтом в «Избранное» или канал.

> ⚠️ Автоматизация юзер-аккаунта формально против ToS Telegram. Используй **отдельный
> номер**, не основной.

## Сервисы (docker-compose)

- `vpn_userbot` — `python -m vpndigest.ingest` (live-листенер)
- `vpn_digest_worker` — `python -m vpndigest.worker` (APScheduler по `VPN_DIGEST_CRON`)

## Переменные в `.env` (добавить к существующим)

```
# Telegram userbot (TG_API_ID/TG_API_HASH уже есть для history_load)
TG_API_ID=
TG_API_HASH=
VPN_SESSION_STRING=             # из `python -m vpndigest.login`
VPN_MONITORED_CHAT_IDS=         # csv: -1001234567890,@some_chat

# Доставка / расписание
VPN_DIGEST_TARGET_CHAT=me       # "me" = Избранное, либо @канал / chat_id
VPN_DIGEST_CRON=0 9 * * *
VPN_DIGEST_WINDOW_HOURS=24
VPN_BACKFILL_DAYS=7

# LLM (через общий ai_client / OpenCode)
VPN_DIGEST_MODEL=opencode-go/qwen3.5-plus
```

## Первый запуск

```bash
# 1) сессия с ОТДЕЛЬНОГО аккаунта (локально, интерактивно) -> в .env как VPN_SESSION_STRING
python -m vpndigest.login

# 2) указать VPN_MONITORED_CHAT_IDS в .env

# 3) накатить миграцию (новые таблицы vpn_*)
alembic upgrade head            # или: docker compose run --rm migrations

# 4) подтянуть историю и зарегистрировать чаты
python -m vpndigest.backfill

# 5) проверить дайджест разово
python -m vpndigest.worker --once

# 6) поднять сервисы
docker compose up -d vpn_userbot vpn_digest_worker
```

## Дальше (вне MVP)

База знаний/FAQ: у проекта уже есть pgvector + `common/models/message_embedding.py` —
эмбеддить `vpn_messages` и искать «проблема → решение».
