"""Авто-скачивание TikTok / Reels / Shorts по ссылке в чате.

Платно: списывает гривны с автора ссылки в банк чата (sink). При
неудаче — возврат. Роутер подключать ДО message_router (catch-all
в messages.py иначе перехватит).
"""
import asyncio
import os

from aiogram import F, Router, types
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.user import User
from services.markets_service import InsufficientFunds
from services.media_dl_service import (
    MEDIADL_COST,
    charge,
    download_sync,
    extract_url,
    refund,
)

logger = get_logger(__name__)
router = Router()

_URL_FILTER = r"https?://\S*(?:tiktok\.com|instagram\.com|youtube\.com/shorts|youtu\.be)\S*"


def _db_user_id(tg_user: types.User | None) -> int | None:
    if not tg_user:
        return None
    session = SessionLocal()
    try:
        u = session.query(User).filter(User.tg_id == tg_user.id).first()
        if u is None:
            full = ((tg_user.first_name or "") + (
                " " + tg_user.last_name if tg_user.last_name else ""
            )).strip()
            u = User(tg_id=tg_user.id, username=tg_user.username, fullname=full or None)
            session.add(u)
            session.commit()
            session.refresh(u)
        return u.id
    except Exception:
        session.rollback()
        logger.exception("media_dl: ensure user failed")
        return None
    finally:
        session.close()


@router.message(F.text.regexp(_URL_FILTER))
async def auto_download(msg: types.Message):
    url = extract_url(msg.text)
    if not url or not msg.from_user:
        return
    user_id = _db_user_id(msg.from_user)
    if user_id is None:
        return

    progress = await msg.reply(f"Скачиваю видео… (−{MEDIADL_COST}г)")

    # Списываем заранее; при неудаче вернём.
    try:
        new_bal = await asyncio.to_thread(charge, user_id, msg.chat.id)
    except InsufficientFunds as exc:
        await progress.edit_text(f"Не хватает гривен: {exc}")
        return
    except Exception:
        logger.exception("media_dl charge failed")
        await progress.edit_text("Не удалось списать оплату.")
        return

    items, err = await asyncio.to_thread(download_sync, url)
    if err or not items:
        await asyncio.to_thread(refund, user_id, msg.chat.id)
        await progress.edit_text(f"{err or 'Не удалось скачать'} (деньги возвращены).")
        return

    # Кто скинул — для подписи (исходное сообщение со ссылкой удалим,
    # поэтому ссылку на оригинал кладём в подпись бота).
    u = msg.from_user
    who = ("@" + u.username) if u and u.username else (
        (u.first_name or "кто-то") if u else "кто-то"
    )
    caption = f"📥 от {who} · −{MEDIADL_COST}г\n{url}"
    try:
        if len(items) == 1:
            path, mtype = items[0]
            if mtype == "photo":
                await msg.bot.send_photo(
                    chat_id=msg.chat.id,
                    photo=FSInputFile(path),
                    caption=caption,
                )
            else:
                await msg.bot.send_video(
                    chat_id=msg.chat.id,
                    video=FSInputFile(path),
                    caption=caption,
                )
        else:
            media = []
            for i, (path, mtype) in enumerate(items):
                cap = caption if i == 0 else None
                file = FSInputFile(path)
                if mtype == "photo":
                    media.append(InputMediaPhoto(media=file, caption=cap))
                else:
                    media.append(InputMediaVideo(media=file, caption=cap))
            await msg.bot.send_media_group(chat_id=msg.chat.id, media=media)
        # Удаляем исходное сообщение со ссылкой + прогресс
        try:
            await msg.delete()
        except Exception:
            pass
        await progress.delete()
    except Exception:
        logger.exception("media_dl send failed")
        await asyncio.to_thread(refund, user_id, msg.chat.id)
        await progress.edit_text(
            "Не удалось отправить в Telegram (возможно >50МБ). Деньги возвращены."
        )
    finally:
        for path, _ in items:
            try:
                os.remove(path)
            except OSError:
                pass
