"""Социальный магазин: poke/hug, анекдот на заказ, AI-роаст.

Все действия списывают гривны с инициатора в банк чата (sink против
инфляции фермы) и постят результат в чат через Bot API.
"""
import json
import os
import urllib.parse
import urllib.request
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
from services.summary_service import get_summary_model

logger = get_logger(__name__)


def _ai_call(*args, **kwargs) -> str:
    """Ленивый импорт ai_client: openai тяжёлый и не нужен пока не вызовут
    joke/roast. Так API стартует даже без пакета, а poke работает всегда."""
    from services.ai_client import call as ai_call

    return ai_call(*args, **kwargs)


POKE_COST = int(os.getenv("SOCIAL_POKE_COST", "50"))
JOKE_COST = int(os.getenv("SOCIAL_JOKE_COST", "150"))
ROAST_COST = int(os.getenv("SOCIAL_ROAST_COST", "300"))

POKE_TEMPLATES = {
    "poke": "{actor} пнул(а) {target} — отрабатывай долги!",
    "hug": "{actor} крепко обнял(а) {target}",
    "highfive": "{actor} дал(а) пять {target}",
}


def _bot_token() -> str:
    t = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("TELEGRAM_TOKEN не задан")
    return t


def send_chat_message(chat_id: int, text: str) -> None:
    """Bot API sendMessage (синхронно, оборачивать в asyncio.to_thread)."""
    url = f"https://api.telegram.org/bot{_bot_token()}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"User-Agent": "xyloz-bot-api/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            logger.warning("sendMessage failed: %s", body)
    except Exception:
        logger.exception("sendMessage error chat=%s", chat_id)


def _charge(user_id: int, chat_id: int, amount: int, kind: str, note: str) -> int:
    """Атомарно: списать с юзера → в банк чата (sink). Возвращает новый баланс."""
    if amount <= 0:
        raise InvalidArgument("Цена должна быть положительной")
    session = SessionLocal()
    try:
        bal = _get_or_create_balance(session, user_id, chat_id)
        if bal.balance < amount:
            raise InsufficientFunds(f"Нужно {amount}, у тебя {bal.balance}")
        bank = _get_or_create_bank(session, chat_id)
        now = datetime.utcnow()
        bal.balance -= amount
        bal.updated_at = now
        bank.balance += amount
        bank.updated_at = now
        _log_tx(session, user_id, chat_id, -amount, kind=kind, note=note)
        _log_tx(session, None, chat_id, amount, kind=f"{kind}_to_bank", note=note)
        session.commit()
        return bal.balance
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def do_poke(user_id: int, chat_id: int, actor: str, target: str, kind: str) -> dict:
    if kind not in POKE_TEMPLATES:
        raise InvalidArgument("Неизвестное действие")
    new_bal = _charge(user_id, chat_id, POKE_COST, "social_poke", f"{kind} -> {target}")
    text = POKE_TEMPLATES[kind].format(actor=actor, target=target)
    send_chat_message(chat_id, text)
    return {"text": text, "cost": POKE_COST, "user_balance": new_bal}


def do_joke(user_id: int, chat_id: int, actor: str, topic: str) -> dict:
    topic = (topic or "").strip()[:120]
    if len(topic) < 2:
        raise InvalidArgument("Тема слишком короткая")
    new_bal = _charge(user_id, chat_id, JOKE_COST, "social_joke", topic)
    try:
        body = _ai_call(
            f"Сочини один короткий смешной анекдот на тему: «{topic}». "
            f"Только анекдот, без вступлений и пояснений.",
            get_summary_model(),
            "Ты остроумный комик. Пиши коротко, по-русски, без морали.",
        ).strip()
    except Exception:
        logger.exception("joke gen failed")
        body = "(не получилось придумать — но деньги ушли в банк чата, спасибо)"
    text = f"Анекдот по заказу {actor} (тема: {topic}):\n\n{body}"
    send_chat_message(chat_id, text)
    return {"text": text, "cost": JOKE_COST, "user_balance": new_bal}


def do_roast(user_id: int, chat_id: int, actor: str, target: str) -> dict:
    new_bal = _charge(user_id, chat_id, ROAST_COST, "social_roast", f"-> {target}")
    try:
        body = _ai_call(
            f"Зло, но смешно подколи участника чата {target}. Один абзац, "
            f"дружеский «прожарка»-стиль, без настоящих оскорблений и грубой "
            f"матерщины, по-русски.",
            get_summary_model(),
            "Ты ведущий комеди-прожарки. Остро, иронично, по-доброму едко.",
        ).strip()
    except Exception:
        logger.exception("roast gen failed")
        body = f"{target}, тебе сегодня повезло — генератор прожарки сдох. Деньги в банк."
    text = f"🔥 Прожарка от {actor} → {target}:\n\n{body}"
    send_chat_message(chat_id, text)
    return {"text": text, "cost": ROAST_COST, "user_balance": new_bal}
