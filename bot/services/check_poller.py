"""Поллер xyloz-check: тянет новые диагностики с панели (РФ, до Telegram не достаёт)
и шлёт их в служебный канал. Запускается из scheduler каждые ~30с.

Env: CHECK_URL (https://check.xyloz.ru), CHECK_TOKEN (ADMIN_TOKEN), CHECK_CHAT (id канала).
"""
import os

import aiohttp
from aiogram import Bot

from common.logger.logger import get_logger

log = get_logger(__name__)

CHECK_URL = (os.getenv("CHECK_URL") or "").rstrip("/")
CHECK_TOKEN = os.getenv("CHECK_TOKEN") or ""
CHECK_CHAT = os.getenv("CHECK_CHAT") or ""


def _chat():
    return int(CHECK_CHAT) if CHECK_CHAT.lstrip("-").isdigit() else CHECK_CHAT


async def poll_check_once(bot: Bot) -> None:
    if not (CHECK_URL and CHECK_TOKEN and CHECK_CHAT):
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{CHECK_URL}/api/pending",
                params={"token": CHECK_TOKEN},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    log.warning("check_poller: /api/pending -> %s", r.status)
                    return
                data = await r.json()
    except Exception:
        log.warning("check_poller: не достучался до %s", CHECK_URL)
        return

    for item in data.get("items", []):
        try:
            await bot.send_message(
                _chat(), item["text"], parse_mode="HTML", disable_web_page_preview=True
            )
        except Exception:
            log.exception("check_poller: не смог отправить в %s", CHECK_CHAT)
