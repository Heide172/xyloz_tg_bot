from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from common.logger.logger import get_logger
from services.digest_service import (
    find_active_chat_ids,
    generate_digest,
    has_data_for_period,
)

logger = get_logger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TG_CHUNK = 3900


def _split_chunks(text: str, chunk_size: int = TG_CHUNK) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    i = 0
    while i < len(text):
        end = min(i + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind("\n", i, end)
            if split_at > i + 200:
                end = split_at + 1
        chunks.append(text[i:end].rstrip())
        i = end
    return chunks


async def _weekly_digest_job(bot: Bot) -> None:
    chat_ids = find_active_chat_ids(window_days=14)
    logger.info("weekly digest: checking %d active chats", len(chat_ids))
    for chat_id in chat_ids:
        if not has_data_for_period(chat_id, days=7):
            continue
        try:
            text = await generate_digest(chat_id=chat_id, days=7)
            for chunk in _split_chunks(text):
                await bot.send_message(chat_id, chunk)
            logger.info("weekly digest sent to chat %s", chat_id)
        except Exception:
            logger.exception("weekly digest failed for chat %s", chat_id)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(
        _weekly_digest_job,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=MOSCOW_TZ),
        args=(bot,),
        id="weekly_digest",
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("scheduler started: weekly digest at Mon 09:00 MSK")
    return scheduler
