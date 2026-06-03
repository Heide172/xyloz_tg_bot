"""Подтянуть историю monitored-чатов за последние VPN_BACKFILL_DAYS дней.

    python -m vpndigest.backfill
    python -m vpndigest.backfill --days 14
"""
import argparse
import asyncio
from datetime import datetime, timedelta

from common.logger import get_logger
from vpndigest import config
from vpndigest.client import build_client
from vpndigest.ingest import normalize, _utc_naive
from vpndigest.storage import store_messages, register_chat

log = get_logger("vpndigest.backfill")

_BATCH = 200


async def _backfill_chat(app, peer, since: datetime) -> int:
    chat = await app.get_chat(peer)
    register_chat(chat)
    log.info("Бэкфилл «%s» (id=%s, forum=%s)", getattr(chat, "title", chat.id), chat.id,
             getattr(chat, "is_forum", False))

    saved = 0
    batch: list[dict] = []
    async for m in app.get_chat_history(chat.id):
        # m.date может быть naive или aware (зависит от версии Pyrogram);
        # приводим к naive-UTC, как и since (и как хранится в БД).
        msg_date = _utc_naive(m.date)
        if msg_date and msg_date < since:
            break
        row = normalize(m)
        if row:
            batch.append(row)
        if len(batch) >= _BATCH:
            saved += store_messages(batch)
            batch.clear()
    if batch:
        saved += store_messages(batch)
    log.info("  сохранено: %d", saved)
    return saved


async def main(days: int):
    if not config.MONITORED_CHAT_IDS:
        raise SystemExit("VPN_MONITORED_CHAT_IDS пуст — заполни .env")
    since = datetime.utcnow() - timedelta(days=days)  # naive-UTC, как created_at в БД
    app = build_client(name="vpn_digest_backfill")
    total = 0
    async with app:
        # Прогрев кэша пиров: на in-memory сессии резолв по chat_id не работает,
        # пока Pyrogram не увидит диалоги (см. resolve_peer в history_load.py).
        warmed = 0
        async for _ in app.get_dialogs():
            warmed += 1
        log.info("Кэш диалогов прогрет: %d", warmed)

        for peer in config.MONITORED_CHAT_IDS:
            try:
                total += await _backfill_chat(app, peer, since)
            except Exception:
                log.exception("Не смог забэкфиллить %s", peer)
    log.info("Готово. Всего: %d сообщений за %d дн.", total, days)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.VPN_BACKFILL_DAYS)
    args = ap.parse_args()
    asyncio.run(main(args.days))
