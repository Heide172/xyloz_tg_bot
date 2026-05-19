"""Админ-модерация обратной связи: /fb list | show | done.

Закрытие бага/идеи начисляет автору награду (эмиссия) на баланс в
чате, откуда фидбэк прислан. Роутер подключать ДО message_router.
"""
import asyncio
import html

from aiogram import Router, types
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.feedback_service import (
    REWARD_BUG,
    REWARD_IDEA,
    close,
    get_one,
    list_open,
)
from services.social_service import send_chat_message

router = Router()
logger = get_logger(__name__)

HELP = (
    "Модерация обратной связи:\n"
    "  /fb list                — открытые заявки\n"
    "  /fb show <id>           — полный текст\n"
    "  /fb done <id> [сумма]   — закрыть + наградить автора\n"
    f"\nНаграда по умолчанию: баг {REWARD_BUG}г, идея {REWARD_IDEA}г.\n"
    "сумма=0 — закрыть без награды."
)


def _ok(msg: types.Message) -> bool:
    return bool(msg.from_user and is_admin_tg_id(msg.from_user.id))


async def _mono(msg: types.Message, text: str):
    await msg.answer(f"<pre>{html.escape(text)}</pre>", parse_mode="HTML")


@router.message(Command("fb"))
async def cmd_fb(msg: types.Message):
    if not _ok(msg):
        await msg.answer("Только для админов бота.")
        return

    parts = (msg.text or "").split()
    sub = parts[1].lower() if len(parts) > 1 else "list"

    if sub in ("list", "ls"):
        rows = await asyncio.to_thread(list_open, 20)
        if not rows:
            await msg.answer("Открытых заявок нет.")
            return
        lines = ["Открытая обратная связь:", ""]
        for r in rows:
            icon = "BUG " if r["kind"] == "bug" else "IDEA"
            preview = r["text"].replace("\n", " ")[:80]
            lines.append(f"#{r['id']} [{icon}] {preview}")
        lines.append("")
        lines.append("Полный текст: /fb show <id>")
        await _mono(msg, "\n".join(lines))
        return

    if sub == "show":
        if len(parts) < 3 or not parts[2].isdigit():
            await msg.answer("Укажи id: /fb show 12")
            return
        r = await asyncio.to_thread(get_one, int(parts[2]))
        if not r:
            await msg.answer("Заявка не найдена.")
            return
        head = (
            f"#{r['id']} · {r['kind']} · {r['status']} · "
            f"chat={r['chat_id']} · reward={r['reward']}"
        )
        await _mono(msg, f"{head}\n\n{r['text']}")
        return

    if sub in ("done", "close"):
        if len(parts) < 3 or not parts[2].isdigit():
            await msg.answer("Укажи id: /fb done 12 [сумма]")
            return
        fid = int(parts[2])
        amount = None
        if len(parts) >= 4:
            try:
                amount = int(parts[3])
            except ValueError:
                await msg.answer("Сумма должна быть числом.")
                return
        res = await asyncio.to_thread(close, fid, amount)
        if not res.get("ok"):
            err = res.get("error")
            if err == "already_done":
                await msg.answer(
                    f"#{fid} уже закрыта (награда была {res.get('reward', 0)}г)."
                )
            elif err == "not_found":
                await msg.answer("Заявка не найдена.")
            else:
                await msg.answer("Не удалось закрыть (см. логи).")
            return

        reward = res["reward"]
        who = res.get("author_name") or "автор"
        if res.get("credited"):
            await msg.answer(
                f"#{fid} закрыта. {who} получил +{reward}г в чате "
                f"{res.get('chat_id')}."
            )
        else:
            await msg.answer(
                f"#{fid} закрыта без выплаты "
                f"(нет чата/автора или сумма 0)."
            )

        # Уведомить автора в ЛС (best-effort).
        atg = res.get("author_tg_id")
        if atg and res.get("credited"):
            kind_ru = "баг" if res["kind"] == "bug" else "идею"
            note = (
                f"Спасибо за {kind_ru}! Заявка #{fid} закрыта, "
                f"тебе начислено +{reward}г."
            )
            try:
                await asyncio.to_thread(send_chat_message, atg, note)
            except Exception:
                logger.warning("feedback notify author %s failed", atg)
        return

    await _mono(msg, HELP)
