"""Валидация Telegram WebApp initData через HMAC bot_token + проверка членства в чате.

См. https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException, Header, Query, Request

INIT_DATA_MAX_AGE_SEC = int(os.getenv("TMA_INIT_DATA_MAX_AGE", "86400"))  # 24h


@dataclass
class TgWebAppUser:
    id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None


@dataclass
class TgWebAppAuth:
    user: TgWebAppUser
    auth_date: int
    chat_id: int | None  # из query параметра


def _bot_token() -> str:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    return token


def _verify_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="missing initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    sent_hash = pairs.pop("hash", None)
    if not sent_hash:
        raise HTTPException(status_code=401, detail="initData: no hash")

    sorted_pairs = sorted(pairs.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)

    secret_key = hmac.new(b"WebAppData", _bot_token().encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, sent_hash):
        raise HTTPException(status_code=401, detail="initData: hash mismatch")

    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date and time.time() - auth_date > INIT_DATA_MAX_AGE_SEC:
        raise HTTPException(status_code=401, detail="initData: too old")

    return pairs


async def require_auth(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    chat_id: int | None = Query(default=None),
) -> TgWebAppAuth:
    init_data = x_telegram_init_data or request.query_params.get("init_data")
    pairs = _verify_init_data(init_data or "")

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="initData: no user")
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="initData: malformed user")

    tg_user = TgWebAppUser(
        id=int(user_obj.get("id")),
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
        language_code=user_obj.get("language_code"),
    )
    return TgWebAppAuth(user=tg_user, auth_date=int(pairs.get("auth_date") or 0), chat_id=chat_id)


def ensure_db_user(auth: TgWebAppAuth) -> int:
    from common.db.db import SessionLocal
    from common.models.user import User

    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == auth.user.id).first()
        if u is None:
            full_name = (auth.user.first_name or "") + (
                (" " + auth.user.last_name) if auth.user.last_name else ""
            )
            u = User(
                tg_id=auth.user.id,
                username=auth.user.username,
                fullname=full_name.strip() or None,
            )
            session.add(u)
            session.commit()
            session.refresh(u)
        return u.id
    finally:
        session.close()


def require_chat_id(auth: TgWebAppAuth) -> int:
    if auth.chat_id is None:
        raise HTTPException(status_code=400, detail="chat_id query param required")
    return auth.chat_id


# ---------------- chat membership ----------------

MEMBERSHIP_CACHE_TTL_SEC = int(os.getenv("TMA_MEMBERSHIP_CACHE_TTL", "300"))
_membership_cache: dict[tuple[int, int], tuple[bool, float]] = {}
_membership_lock = asyncio.Lock()


def _is_member_sync(chat_id: int, user_tg_id: int) -> bool:
    """Прямой HTTP-запрос Bot API: getChatMember.
    True если юзер состоит в чате (creator / administrator / member / restricted).
    """
    token = _bot_token()
    base = f"https://api.telegram.org/bot{token}/getChatMember"
    params = urllib.parse.urlencode({"chat_id": chat_id, "user_id": user_tg_id})
    req = urllib.request.Request(
        f"{base}?{params}",
        method="GET",
        headers={"User-Agent": "xyloz-bot-api/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    if not body.get("ok"):
        return False
    status_str = (body.get("result") or {}).get("status") or ""
    return status_str in ("creator", "administrator", "member", "restricted")


async def is_chat_member(chat_id: int, user_tg_id: int) -> bool:
    """Кэшированная проверка членства. TTL 5 минут (env TMA_MEMBERSHIP_CACHE_TTL)."""
    now = time.time()
    key = (chat_id, user_tg_id)
    cached = _membership_cache.get(key)
    if cached and now - cached[1] < MEMBERSHIP_CACHE_TTL_SEC:
        return cached[0]
    async with _membership_lock:
        cached = _membership_cache.get(key)
        if cached and now - cached[1] < MEMBERSHIP_CACHE_TTL_SEC:
            return cached[0]
        ok = await asyncio.to_thread(_is_member_sync, chat_id, user_tg_id)
        _membership_cache[key] = (ok, now)
        return ok


async def require_chat_membership(auth: TgWebAppAuth) -> int:
    chat_id = require_chat_id(auth)
    ok = await is_chat_member(chat_id, auth.user.id)
    if not ok:
        raise HTTPException(status_code=403, detail="Ты не состоишь в этом чате.")
    return chat_id
