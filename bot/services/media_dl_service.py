"""Скачивание видео (TikTok / Instagram Reels / YT Shorts) через self-host
cobalt API (обходит датацентр-блоки на своей стороне).

Платная операция: списывает гривны с автора ссылки в банк чата (sink).
При неудаче скачивания — деньги возвращаются.
"""
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
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
COBALT_API = (os.getenv("COBALT_API_URL", "http://cobalt:9000/")).rstrip("/") + "/"

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


def _cobalt_resolve(url: str) -> tuple[str | None, str | None]:
    """Спрашивает cobalt прямую ссылку на медиа. (media_url, error)."""
    body = json.dumps({"url": url, "videoQuality": "720"}).encode()
    req = urllib.request.Request(
        COBALT_API,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "xyloz-bot/1.0",
        },
    )
    data = None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # cobalt при ошибке отдаёт 400 с JSON {status:error, error:{code}}
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            logger.warning("cobalt HTTP %s no body for %s", exc.code, url)
            return None, "Не удалось обработать ссылку."
    except Exception as exc:
        logger.warning("cobalt unreachable for %s: %s", url, str(exc)[:200])
        return None, "Сервис скачивания недоступен (попробуй позже)."

    status = data.get("status")
    if status in ("tunnel", "redirect"):
        return data.get("url"), None
    if status == "picker":
        items = data.get("picker") or []
        vid = next((i for i in items if i.get("type") == "video"), None)
        chosen = (vid or (items[0] if items else {})).get("url")
        if chosen:
            return chosen, None
        return None, "Нечего скачивать (пустой ответ)."
    if status == "local-processing":
        return None, "Этот ролик требует склейки на клиенте — не поддерживается."

    err = str((data.get("error") or {}).get("code", "")).lower()
    logger.warning("cobalt status=%s err=%s url=%s", status, err, url)
    if "youtube" in err or "not a bot" in err or "token" in err:
        return None, (
            "YouTube не отдаёт видео с сервера (антибот). "
            "Кидай TikTok — он качается надёжно."
        )
    if "auth" in err or "private" in err or "login" in err:
        return None, "Видео приватное / требует логина."
    if "unsupported" in err or "link" in err:
        return None, "Эта ссылка не поддерживается для скачивания."
    return None, "Не удалось получить видео (сайт не отдал)."


def download_sync(url: str) -> tuple[str | None, str | None]:
    """Резолвит ссылку через cobalt и качает файл ≤MAX_BYTES.
    Вызывать в asyncio.to_thread — операция блокирующая и долгая."""
    media_url, err = _cobalt_resolve(url)
    if err or not media_url:
        return None, err or "Не удалось получить видео."

    tmpdir = tempfile.gettempdir()
    path = os.path.join(tmpdir, f"mdl_{uuid.uuid4().hex}.mp4")
    req = urllib.request.Request(
        media_url, headers={"User-Agent": "xyloz-bot/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = 0
            with open(path, "wb") as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        f.close()
                        os.remove(path)
                        return None, (
                            f"Видео больше {MAX_BYTES // 1024 // 1024} МБ "
                            f"(лимит Telegram)."
                        )
                    f.write(chunk)
        if total == 0:
            os.remove(path)
            return None, "Пустой файл."
        return path, None
    except Exception as exc:
        logger.warning("media fetch failed for %s: %s", url, str(exc)[:200])
        try:
            os.remove(path)
        except OSError:
            pass
        return None, "Не удалось скачать файл."
