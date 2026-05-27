"""Listener-логика двойника: should_reply + craft_reply + post_reply.

Использует state из twin_service.get_state() + персональную статистику
target'а из persona_stats для адаптивного pacing (burst, час, длина, lag).

LLM — opencode-go через ai_client. Маркировка — весь ответ italic
(parse_mode=HTML, обёрнут в <i>...</i>; небезопасные < > & экранируются).

Без toxicity-gate (двойник копирует стиль как есть).
"""
import asyncio
import os
import random
import time
from datetime import datetime, timedelta
from html import escape as html_escape

from aiogram import Bot

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_twin_state import ChatTwinState
from common.models.message import Message
from common.models.twin_log import TwinLog
from services import ai_client
from services.summary_service import get_summary_model

logger = get_logger(__name__)

# Тюнинг через env, дефолты — стартовые
ENABLED = os.getenv("TWIN_ACTIVE_ENABLED", "false").lower() == "true"
RAND_P = float(os.getenv("TWIN_RAND_P", "0.06"))
COOLDOWN_S = int(os.getenv("TWIN_COOLDOWN_S", "90"))
MAX_PER_HOUR = int(os.getenv("TWIN_MAX_PER_HOUR", "8"))
MAX_PER_DAY = int(os.getenv("TWIN_MAX_PER_DAY", "50"))
MIN_REPLY_CHARS = int(os.getenv("TWIN_MIN_REPLY_CHARS", "6"))
MAX_REPLY_CHARS = int(os.getenv("TWIN_MAX_REPLY_CHARS", "300"))
CHAT_CONTEXT_N = int(os.getenv("TWIN_CHAT_CTX", "8"))
TAIL_RECENCY_N = int(os.getenv("TWIN_TAIL_N", "30"))
LAG_NOISE_PCT = 0.3
LAG_MIN = 5
LAG_MAX = 90
DEFAULT_MODEL = os.getenv("TWIN_MODEL", "")  # пустая = get_summary_model()
REPLY_COST = int(os.getenv("TWIN_REPLY_COST", "30"))  # списывается из банка чата


# In-memory burst-трекер: chat_id → list[timestamp last_msg]
_burst: dict[int, list[float]] = {}
# Кеш per-hour счётчика: (chat_id, hour_key) → count
_hour_counter: dict[tuple[int, str], int] = {}


def _burst_score(chat_id: int, window_s: int = 300) -> int:
    """Сколько сообщений в этом чате за последние window_s секунд."""
    now = time.time()
    buf = _burst.get(chat_id, [])
    buf = [t for t in buf if now - t <= window_s]
    _burst[chat_id] = buf
    return len(buf)


def note_message(chat_id: int) -> None:
    """Отметить, что в чате пришло новое сообщение (для burst-детектора)."""
    _burst.setdefault(chat_id, []).append(time.time())


def _hour_key(chat_id: int) -> tuple[int, str]:
    return chat_id, datetime.utcnow().strftime("%Y-%m-%dT%H")


def _per_hour_count(chat_id: int) -> int:
    return _hour_counter.get(_hour_key(chat_id), 0)


def _inc_per_hour(chat_id: int) -> None:
    k = _hour_key(chat_id)
    _hour_counter[k] = _hour_counter.get(k, 0) + 1


def _msk_hour() -> int:
    return (datetime.utcnow().hour + 3) % 24


def should_reply(state: dict, message_text: str, mentions: list[str],
                 is_reply_to_target: bool, from_user_id: int | None) -> bool:
    """Решает, отвечать ли. state — снимок ChatTwinState из get_state()."""
    if not ENABLED or not state:
        return False
    if not state.get("target_user_id") or not state.get("enabled"):
        return False
    if state.get("paused_until"):
        try:
            if datetime.fromisoformat(state["paused_until"]) > datetime.utcnow():
                return False
        except Exception:
            pass
    # самому себе не отвечаем (не зацикливаемся)
    if from_user_id is not None and from_user_id == state["target_user_id"]:
        return False
    text = (message_text or "").strip()
    if len(text) < 2:
        return False
    # дневной лимит
    if state.get("replies_today", 0) >= MAX_PER_DAY:
        return False
    # часовой лимит
    if _per_hour_count(state["chat_id"]) >= MAX_PER_HOUR:
        return False
    # cooldown
    last = state.get("last_reply_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except Exception:
            last_dt = None
        if last_dt:
            burst = _burst_score(state["chat_id"])
            cd = COOLDOWN_S // 2 if burst >= 10 else COOLDOWN_S
            if datetime.utcnow() - last_dt < timedelta(seconds=cd):
                return False

    # mention или reply на двойника → высокий шанс
    target_uname = (state.get("target_name") or "").lstrip("@").lower()
    if target_uname and any(m.lower() == target_uname for m in mentions):
        return random.random() < 0.85
    if is_reply_to_target:
        return random.random() < 0.85

    # базовая вероятность с модификаторами
    stats = state.get("persona_stats") or {}
    p = RAND_P
    burst = _burst_score(state["chat_id"])
    if burst >= 10:
        p *= 2.0
    elif burst <= 2:
        p *= 0.5
    active_hours = stats.get("active_hours_msk") or []
    cur_h = _msk_hour()
    if cur_h in active_hours:
        p *= 1.3
    # ночь (00-06 MSK) и не активный час
    if 0 <= cur_h < 6 and cur_h not in active_hours:
        p *= 0.4
    return random.random() < p


def _fetch_target_tail(target_user_id: int, chat_id: int, n: int) -> list[str]:
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.text)
            .filter(
                Message.user_id == target_user_id,
                Message.chat_id == chat_id,
                Message.text.isnot(None),
            )
            .order_by(Message.created_at.desc())
            .limit(n)
            .all()
        )
        return [r[0].strip() for r in rows if r[0] and r[0].strip()]
    finally:
        session.close()


def _fetch_chat_context(chat_id: int, before_id: int | None, n: int) -> list[tuple[str, str]]:
    """Последние n сообщений в чате до триггера. (author_label, text)."""
    session = SessionLocal()
    try:
        from common.models.user import User

        q = (
            session.query(Message, User)
            .outerjoin(User, Message.user_id == User.id)
            .filter(Message.chat_id == chat_id, Message.text.isnot(None))
        )
        if before_id is not None:
            q = q.filter(Message.telegram_message_id <= before_id)
        rows = q.order_by(Message.created_at.desc()).limit(n).all()
        out = []
        for msg, user in reversed(rows):
            who = (
                (user.username if user and user.username else None)
                or (user.fullname if user and user.fullname else None)
                or "?"
            )
            out.append((who, (msg.text or "").strip()))
        return out
    finally:
        session.close()


def _build_prompt(state: dict, trigger_text: str, trigger_author: str,
                  tail: list[str], context: list[tuple[str, str]]) -> tuple[str, str]:
    name = state.get("target_name") or "?"
    stats = state.get("persona_stats") or {}
    avg_len = int(stats.get("avg_msg_len") or 80)
    sys_prompt = (
        f"Ты подражаешь стилю участника чата @{name}. Отвечай как он "
        f"в чате с друзьями, естественно, как настоящий человек. "
        f"Не выдумывай факты о его жизни. Сохраняй его уровень "
        f"токсичности и юмора. Длина — около {avg_len} символов, "
        f"максимум {MAX_REPLY_CHARS}. Не используй имя «{name}» от третьего "
        f"лица — ты и есть он. Никаких пояснений про себя как ИИ."
    )

    tail_block = "\n".join(f"- {t}" for t in tail[:TAIL_RECENCY_N])
    ctx_block = "\n".join(f"{a}: {t}" for a, t in context[-CHAT_CONTEXT_N:])

    user_prompt = (
        f"Примеры того, как ты обычно пишешь:\n{tail_block}\n\n"
        f"Сейчас в чате идёт диалог:\n{ctx_block}\n\n"
        f"Последнее сообщение от {trigger_author}: «{trigger_text}»\n\n"
        f"Ответь от первого лица — короткой репликой в твоём стиле."
    )
    return sys_prompt, user_prompt


def _wrap_italic_html(text: str) -> str:
    return f"<i>{html_escape(text.strip())}</i>"


def _persona_lag_seconds(state: dict) -> int:
    stats = state.get("persona_stats") or {}
    base = int(stats.get("avg_response_lag") or 30)
    noise = int(base * LAG_NOISE_PCT)
    return max(LAG_MIN, min(LAG_MAX, base + random.randint(-noise, noise)))


def _model() -> str:
    return DEFAULT_MODEL or get_summary_model()


def craft_reply_sync(state: dict, trigger_text: str, trigger_author: str,
                     before_message_id: int | None) -> str | None:
    """LLM-вызов синхронно (для asyncio.to_thread). Возвращает текст или None."""
    target_uid = state["target_user_id"]
    chat_id = state["chat_id"]
    tail = _fetch_target_tail(target_uid, chat_id, TAIL_RECENCY_N)
    if len(tail) < 5:
        return None  # совсем тонкий корпус — не выдумываем
    context = _fetch_chat_context(chat_id, before_message_id, CHAT_CONTEXT_N)
    sys_prompt, user_prompt = _build_prompt(
        state, trigger_text, trigger_author, tail, context
    )
    try:
        raw = ai_client.call(user_prompt, _model(), sys_prompt)
    except Exception:
        logger.exception("twin LLM call failed chat=%s", chat_id)
        return None
    text = (raw or "").strip()
    # выдрать лишние кавычки/префиксы которые LLM иногда приплетает
    if text.startswith(("«", '"', "'")):
        text = text.lstrip("«\"'").rstrip("»\"'").strip()
    if len(text) < MIN_REPLY_CHARS:
        return None
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS - 1].rstrip() + "…"
    return text


def _charge_bank(chat_id: int, amount: int) -> bool:
    """Списать N гривен из банка чата (sink). True если получилось."""
    if amount <= 0:
        return True
    from common.models.chat_bank import ChatBank
    from common.models.economy_tx import EconomyTx

    session = SessionLocal()
    try:
        bank = (
            session.query(ChatBank)
            .filter(ChatBank.chat_id == chat_id)
            .with_for_update()
            .first()
        )
        if not bank or bank.balance < amount:
            return False
        bank.balance -= amount
        bank.updated_at = datetime.utcnow()
        session.add(EconomyTx(
            user_id=None, chat_id=chat_id, amount=-amount,
            kind="twin_reply_cost", note="двойник дня — оплата ответа",
        ))
        session.commit()
        return True
    except Exception:
        session.rollback()
        logger.exception("twin charge failed chat=%s", chat_id)
        return False
    finally:
        session.close()


async def post_reply(bot: Bot, state: dict, trigger_msg_id: int, text: str) -> bool:
    """Имитирует задержку target'а, списывает банк, отправляет italic-reply,
    обновляет счётчики и лог. Возвращает True если успешно."""
    chat_id = state["chat_id"]
    if not _charge_bank(chat_id, REPLY_COST):
        logger.info("twin: банк чата %s пуст, пропускаем ответ", chat_id)
        _log_to_db(state, trigger_msg_id, text, status="skipped", cost=0)
        return False
    lag = _persona_lag_seconds(state)
    try:
        await asyncio.sleep(lag)
    except asyncio.CancelledError:
        return False
    try:
        await bot.send_message(
            chat_id,
            _wrap_italic_html(text),
            parse_mode="HTML",
            reply_to_message_id=trigger_msg_id,
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("twin send failed chat=%s", chat_id)
        _log_to_db(state, trigger_msg_id, text, status="err", cost=REPLY_COST)
        return False
    _bump_state(chat_id)
    _inc_per_hour(chat_id)
    _log_to_db(state, trigger_msg_id, text, status="sent", cost=REPLY_COST)
    return True


def _bump_state(chat_id: int) -> None:
    session = SessionLocal()
    try:
        s = (
            session.query(ChatTwinState)
            .filter(ChatTwinState.chat_id == chat_id)
            .with_for_update()
            .first()
        )
        if not s:
            return
        s.replies_today = (s.replies_today or 0) + 1
        s.last_reply_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _log_to_db(
    state: dict, trigger_msg_id: int, text: str, status: str, cost: int = 0
) -> None:
    session = SessionLocal()
    try:
        session.add(TwinLog(
            chat_id=state["chat_id"],
            target_user_id=state.get("target_user_id"),
            trigger_message_id=trigger_msg_id,
            response_text=text[:1000],
            cost=cost,
            status=status,
        ))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
