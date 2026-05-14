from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from common.logger.logger import get_logger
from services.digest_service import (
    find_active_chat_ids,
    generate_digest,
    has_data_for_period,
)
from services.embed_worker import embed_pending_once
from services.external_markets import auto_resolve_external
from services.markets_service import auto_close_expired
from services.nlp_classifier import classify_pending_once
from services.nominations_service import run_daily_nominations

logger = get_logger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
TG_CHUNK = 3900

# Module-level reference: используется в admin_status_service для отображения jobs.
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


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
    global _scheduler
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    _scheduler = scheduler
    scheduler.add_job(
        _weekly_digest_job,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=MOSCOW_TZ),
        args=(bot,),
        id="weekly_digest",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        classify_pending_once,
        trigger=IntervalTrigger(seconds=30),
        id="nlp_classify_pending",
        coalesce=True,
        max_instances=1,
        next_run_time=None,
    )
    scheduler.add_job(
        embed_pending_once,
        trigger=IntervalTrigger(seconds=45),
        id="embed_pending",
        coalesce=True,
        max_instances=1,
        next_run_time=None,
    )
    scheduler.add_job(
        run_daily_nominations,
        trigger=CronTrigger(hour=10, minute=0, timezone=MOSCOW_TZ),
        args=(bot,),
        id="daily_nominations",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        auto_resolve_external,
        trigger=IntervalTrigger(minutes=30),
        id="external_markets_check",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        auto_close_expired,
        trigger=IntervalTrigger(minutes=5),
        id="markets_auto_close",
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "scheduler started: weekly digest Mon 09:00 MSK, daily nominations 10:00 MSK, "
        "nlp classify 30s, embed 45s, external markets 30m, auto-close 5m"
    )
    return scheduler
