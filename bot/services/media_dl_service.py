"""Скачивание видео (TikTok / Instagram Reels / YT Shorts) через self-host
cobalt API (обходит датацентр-блоки на своей стороне).

Платная операция: списывает гривны с автора ссылки в банк чата (sink).
При неудаче скачивания — деньги возвращаются.
"""
import html
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


_IG_ID_RE = re.compile(
    r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_CAP_MAX = int(os.getenv("MEDIADL_CAPTION_MAX", "600"))


def fetch_ig_caption(url: str) -> str | None:
    """Best-effort: текст Instagram-поста через embed/captioned-страницу
    (тот же эндпоинт, что дёргает cobalt). Никогда не бросает —
    подпись опциональна, скачивание от неё не зависит."""
    m = _IG_ID_RE.search(url or "")
    if not m:
        return None
    sid = m.group(1)
    req = urllib.request.Request(
        f"https://www.instagram.com/p/{sid}/embed/captioned/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.getcode()
            page = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        logger.warning("ig caption fetch failed for %s: %s", sid, str(exc)[:160])
        return None

    mt = re.search(
        r'<div class="Caption">(.*?)<div class="CaptionComments"', page, re.S
    ) or re.search(r'<div class="Caption">(.*?)</div>', page, re.S)
    if not mt:
        # Диагностика: понять, что именно вернул IG с прод-IP.
        marker = 'class="Caption"' in page
        gated = bool(
            re.search(r"login|loginForm|/accounts/login|age|consent", page, re.I)
        )
        logger.warning(
            "ig caption not found sid=%s http=%s len=%d caption_marker=%s gated=%s",
            sid, code, len(page), marker, gated,
        )
        return None
    raw = re.sub(r'<a class="CaptionUsername".*?</a>', "", mt.group(1), flags=re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\n{3,}", "\n\n", html.unescape(raw)).strip()
    if not text:
        return None
    if len(text) > _CAP_MAX:
        text = text[:_CAP_MAX].rstrip() + "…"
    return text


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


# Telegram media group максимум — 10 элементов.
_MAX_GROUP = 10


def _cobalt_resolve(url: str) -> tuple[list[dict] | None, str | None]:
    """Спрашивает cobalt. Возвращает (items, error), где items — список
    {"type": "video"|"photo"|"auto", "url": str}. Несколько элементов =
    карусель (Instagram-пост с фото/видео)."""
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
        u = data.get("url")
        if not u:
            return None, "Нечего скачивать (пустой ответ)."
        # Тип определим по Content-Type при скачивании.
        return [{"type": "auto", "url": u}], None
    if status == "picker":
        raw = data.get("picker") or []
        items: list[dict] = []
        for it in raw:
            iu = it.get("url")
            if not iu:
                continue
            t = it.get("type")
            items.append({
                "type": t if t in ("video", "photo") else "auto",
                "url": iu,
            })
        if not items:
            return None, "Нечего скачивать (пустой ответ)."
        return items[:_MAX_GROUP], None
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


def _fetch_one(media_url: str, declared_type: str) -> tuple[str | None, str | None, str | None]:
    """Качает один файл ≤MAX_BYTES. Возвращает (path, type, error).
    type — video|photo (определяется по Content-Type если declared=auto)."""
    req = urllib.request.Request(media_url, headers={"User-Agent": "xyloz-bot/1.0"})
    tmpdir = tempfile.gettempdir()
    path = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            mtype = declared_type
            if mtype == "auto":
                if ctype.startswith("image/"):
                    mtype = "photo"
                elif ctype.startswith("video/"):
                    mtype = "video"
                else:
                    mtype = "video"
            ext = ".jpg" if mtype == "photo" else ".mp4"
            path = os.path.join(tmpdir, f"mdl_{uuid.uuid4().hex}{ext}")
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
                        return None, None, (
                            f"Файл больше {MAX_BYTES // 1024 // 1024} МБ "
                            f"(лимит Telegram)."
                        )
                    f.write(chunk)
        if not total:
            os.remove(path)
            return None, None, "Пустой файл."
        return path, mtype, None
    except Exception as exc:
        logger.warning("media fetch failed for %s: %s", media_url, str(exc)[:200])
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        return None, None, "Не удалось скачать файл."


def download_sync(url: str) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Резолвит ссылку через cobalt и качает все медиа (фото/видео карусели).
    Возвращает (items, error), где items — список (path, type).
    Вызывать в asyncio.to_thread — операция блокирующая и долгая."""
    resolved, err = _cobalt_resolve(url)
    if err or not resolved:
        return None, err or "Не удалось получить видео."

    out: list[tuple[str, str]] = []
    last_err = None
    for item in resolved:
        path, mtype, ferr = _fetch_one(item["url"], item.get("type", "auto"))
        if ferr or not path:
            last_err = ferr or "Не удалось скачать файл."
            continue
        out.append((path, mtype))

    if not out:
        return None, last_err or "Не удалось скачать файл."
    return out, None
