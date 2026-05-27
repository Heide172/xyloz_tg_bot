"""Команды управления двойником: /twin_optout, /twin_optin, /twin_pause,
/twin_resume, /twin_status.
"""
import os
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_twin_state import ChatTwinState
from common.models.twin_consent import TwinConsent
from common.models.user import User
from services.twin_service import get_state

logger = get_logger(__name__)
router = Router()


def _admin_tg_ids() -> set[int]:
    out = set()
    for p in (os.getenv("BOT_ADMIN_IDS") or "").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            pass
    return out


def _set_consent(tg_id: int, enabled: bool) -> bool:
    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return False
        row = session.query(TwinConsent).filter(TwinConsent.user_id == u.id).first()
        if not row:
            row = TwinConsent(user_id=u.id, enabled=enabled)
            session.add(row)
        else:
            row.enabled = enabled
            row.updated_at = datetime.utcnow()
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


@router.message(Command("twin_optout"))
async def cmd_optout(message: Message) -> None:
    if not message.from_user:
        return
    ok = _set_consent(message.from_user.id, enabled=False)
    if ok:
        await message.reply(
            "Готово. Ты больше не будешь «двойником дня» ни в одном чате. "
            "Вернуться: /twin_optin"
        )
    else:
        await message.reply("Не удалось. Напиши мне сначала в личку — чтобы я тебя видел.")


@router.message(Command("twin_optin"))
async def cmd_optin(message: Message) -> None:
    if not message.from_user:
        return
    ok = _set_consent(message.from_user.id, enabled=True)
    if ok:
        await message.reply("Готово. Снова участвуешь в ротации двойников.")
    else:
        await message.reply("Не удалось.")


@router.message(Command("twin_pause"))
async def cmd_pause(message: Message) -> None:
    """Админ чата: пауза двойника на 24ч."""
    if not message.from_user or message.from_user.id not in _admin_tg_ids():
        await message.reply("Только админам бота.")
        return
    session = SessionLocal()
    try:
        s = (
            session.query(ChatTwinState)
            .filter(ChatTwinState.chat_id == message.chat.id)
            .with_for_update()
            .first()
        )
        if not s:
            s = ChatTwinState(chat_id=message.chat.id, enabled=True)
            session.add(s)
        s.paused_until = datetime.utcnow() + timedelta(hours=24)
        session.commit()
    except Exception:
        session.rollback()
        await message.reply("Не удалось.")
        return
    finally:
        session.close()
    await message.reply("Двойник дня поставлен на паузу на 24ч.")


@router.message(Command("twin_resume"))
async def cmd_resume(message: Message) -> None:
    if not message.from_user or message.from_user.id not in _admin_tg_ids():
        await message.reply("Только админам бота.")
        return
    session = SessionLocal()
    try:
        s = (
            session.query(ChatTwinState)
            .filter(ChatTwinState.chat_id == message.chat.id)
            .with_for_update()
            .first()
        )
        if s:
            s.paused_until = None
            session.commit()
    except Exception:
        session.rollback()
        await message.reply("Не удалось.")
        return
    finally:
        session.close()
    await message.reply("Двойник дня возобновлён.")


@router.message(Command("twin_status"))
async def cmd_status(message: Message) -> None:
    st = get_state(message.chat.id)
    if not st:
        await message.reply("В этом чате двойник ещё не настраивался.")
        return
    if not st.get("target_user_id"):
        await message.reply("Сегодня нет валидного кандидата на двойника.")
        return
    name = st.get("target_name") or "?"
    replies = st.get("replies_today", 0)
    enabled = "✅" if st.get("enabled") else "❌"
    paused = st.get("paused_until")
    pause_line = f"\nПауза до: {paused}" if paused else ""
    await message.reply(
        f"🎭 Двойник дня: @{name}\n"
        f"Ответов сегодня: {replies}\n"
        f"Активен: {enabled}{pause_line}"
    )
