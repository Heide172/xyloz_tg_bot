"""Доставка готового дайджеста тем же юзер-аккаунтом (Pyrogram)."""
import asyncio

from common.logger import get_logger
from vpndigest import config

log = get_logger("vpndigest.publish")

_MAX_LEN = 4000  # Telegram лимит ~4096


def _chunks(text: str, size: int = _MAX_LEN) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > size:
            parts.append(buf)
            buf = ""
        buf += line + "\n"
    if buf.strip():
        parts.append(buf)
    return parts


async def _send(content: str):
    from vpndigest.client import build_client

    app = build_client(name="vpn_digest_publisher")
    async with app:
        target = config.VPN_DIGEST_TARGET_CHAT
        if target.lstrip("-").isdigit():
            target = int(target)
        for part in _chunks(content):
            await app.send_message(target, part, disable_web_page_preview=True)
    log.info("Дайджест отправлен в %s", config.VPN_DIGEST_TARGET_CHAT)


def deliver(content: str):
    asyncio.run(_send(content))
