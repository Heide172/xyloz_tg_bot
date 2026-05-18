"""Скачивание видео (TikTok / Instagram Reels / YT Shorts) через yt-dlp.

Платная операция: списывает гривны с автора ссылки в банк чата (sink).
При неудаче скачивания — деньги возвращаются.
"""
import os
import re
import tempfile
import uuid
from datetime import datetime

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from services.markets_service import (
    InsufficientFunds,
    InvalidArgument,
    _get_or_create_balance,
    _get_or_create_bank,
    _log_tx,
)

logger = get_logger(__name__)

MEDIADL_COST = int(os.getenv("MEDIADL_COST", "50"))
# Telegram Bot API лимит 50 МБ; берём с запасом.
MAX_BYTES = int(os.getenv("MEDIADL_MAX_MB", "48")) * 1024 * 1024

URL_RE = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.)?"
    r"(?:tiktok\.com|instagram\.com|youtube\.com/shorts|youtu\.be)/\S+",
    re.IGNORECASE,
)


def extract_url(text: str | None) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0) if m else None


def charge(user_id: int, chat_id: int) -> int:
    """Списать MEDIADL_COST с юзера → банк чата. Возвращает новый баланс."""
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < MEDIADL_COST:
            raise InsufficientFunds(
                f"Нужно {MEDIADL_COST} гривен, у тебя {bal.balance}"
            )
        bank = _get_or_create_bank(session, chat_id)
        now = datetime.utcnow()
        bal.balance -= MEDIADL_COST
        bal.updated_at = now
        bank.balance += MEDIADL_COST
        bank.updated_at = now
        _log_tx(session, user_id, chat_id, -MEDIADL_COST, kind="mediadl_charge")
        _log_tx(session, None, chat_id, MEDIADL_COST, kind="mediadl_charge_to_bank")
        session.commit()
        return bal.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def refund(user_id: int, chat_id: int) -> None:
    """Вернуть деньги если скачать не удалось."""
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        bank = _get_or_create_bank(session, chat_id)
        now = datetime.utcnow()
        bal.balance += MEDIADL_COST
        bal.updated_at = now
        bank.balance -= MEDIADL_COST
        bank.updated_at = now
        _log_tx(session, user_id, chat_id, MEDIADL_COST, kind="mediadl_refund")
        _log_tx(session, None, chat_id, -MEDIADL_COST, kind="mediadl_refund_from_bank")
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("mediadl refund failed")
    finally:
        session.close()


def download_sync(url: str) -> tuple[str | None, str | None]:
    """Скачивает видео ≤MAX_BYTES. Возвращает (filepath, error).
    Вызывать в asyncio.to_thread — операция блокирующая и долгая."""
    import yt_dlp

    tmpdir = tempfile.gettempdir()
    base = os.path.join(tmpdir, f"mdl_{uuid.uuid4().hex}")
    opts = {
        "outtmpl": base + ".%(ext)s",
        "format": (
            f"best[ext=mp4][filesize<{MAX_BYTES}]/"
            f"best[filesize<{MAX_BYTES}]/best[ext=mp4]/best"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_BYTES,
        "socket_timeout": 30,
        "retries": 2,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        # найти реально скачанный файл
        path = None
        if info and "requested_downloads" in info and info["requested_downloads"]:
            path = info["requested_downloads"][0].get("filepath")
        if not path:
            for ext in ("mp4", "webm", "mkv", "mov"):
                cand = f"{base}.{ext}"
                if os.path.exists(cand):
                    path = cand
                    break
        if not path or not os.path.exists(path):
            return None, "Не удалось скачать (файл не получен)."
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            os.remove(path)
            return None, f"Видео слишком большое (>{MAX_BYTES // 1024 // 1024} МБ)."
        if size == 0:
            os.remove(path)
            return None, "Пустой файл."
        return path, None
    except Exception as exc:
        msg = str(exc)
        if "filesize" in msg.lower() or "max_filesize" in msg.lower():
            return None, "Видео слишком большое для Telegram."
        logger.warning("yt-dlp failed for %s: %s", url, msg[:200])
        return None, "Не удалось скачать (приватное видео или сайт не отдал)."
