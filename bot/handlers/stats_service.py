from __future__ import annotations

from typing import Optional
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile

from bot.services.stats_service import (
    get_user_stats,
    get_global_stats,
    render_activity_plot_png,
)

router = Router()


def _parse_days(args: str) -> int:
    # /ustats 7  -> 7 дней
    try:
        d = int(args.strip())
        return max(1, min(d, 365))
    except Exception:
        return 30


def _parse_chat_flag(text: str) -> Optional[int]:
    # поддержим "-c <chat_id>"
    # пример: "/stats -c -1001234567890 14"
    parts = text.split()
    if "-c" in parts:
        i = parts.index("-c")
        if i + 1 < len(parts):
            try:
                return int(parts[i + 1])
            except Exception:
                return None
    return None


@router.message(Command("ustats"))
async def cmd_ustats(message: Message, command: CommandObject):
    raw = message.text or ""
    chat_filter = _parse_chat_flag(raw)

    # days: возьмём первое число из аргументов (если есть)
    days = 30
    if command.args:
        for token in command.args.split():
            if token.lstrip("-").isdigit():
                days = _parse_days(token)
                break

    # кого считаем:
    # 1) если команда ответом — по автору реплая
    # 2) иначе по автору команды
    target_tg_id = message.from_user.id
    if message.reply_to_message and message.reply_to_message.from_user:
        target_tg_id = message.reply_to_message.from_user.id

    # если в группе и не задан -c, по умолчанию фильтруем по текущему чату
    chat_id = chat_filter
    if chat_id is None and message.chat and message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id

    st = get_user_stats(tg_id=target_tg_id, chat_id=chat_id, days=days)

    who = st.fullname or st.username or str(st.tg_id)
    scope = f"чат {st.chat_id}" if st.chat_id else "все чаты"
    period = f"{st.from_dt.date()} → {st.to_dt.date()}"

    lines = [
        f"📊 **Статистика пользователя:** {who}",
        f"🗓 Период: {period} • {scope}",
        "",
        f"💬 Сообщений: **{st.total_messages}** (текст: {st.text_messages}, стикеры: {st.stickers}, медиа: {st.media})",
        f"↩️ Реплаи: отправил **{st.replies_sent}**, получил **{st.replies_received}**",
    ]

    if st.favorite_emoji:
        lines.append(f"⭐ Любимый эмодзи: {st.favorite_emoji}")
        top = ", ".join([f"{e}×{c}" for e, c in st.emoji_top[:5]])
        if top:
            lines.append(f"🏅 Топ эмодзи: {top}")
    else:
        lines.append("⭐ Любимый эмодзи: —")

    # реакции (частично “за всё время”)
    lines.append(f"👍 Реакции поставил: **{st.reactions_given}** (любимая: {st.favorite_reaction or '—'})")
    lines.append(f"🎯 Реакций на его сообщения (примерно): **{st.reactions_received}**")

    await message.answer("\n".join(lines), parse_mode="Markdown")

    # график активности
    if st.activity_daily:
        png = render_activity_plot_png(
            st.activity_daily,
            title=f"Активность: {who} ({days}д)"
        )
        await message.answer_photo(
            BufferedInputFile(png, filename="activity.png"),
            caption="📈 Активность по дням"
        )


@router.message(Command("stats"))
async def cmd_stats(message: Message, command: CommandObject):
    raw = message.text or ""
    chat_filter = _parse_chat_flag(raw)

    days = 30
    if command.args:
        for token in command.args.split():
            if token.lstrip("-").isdigit():
                days = _parse_days(token)
                break

    chat_id = chat_filter
    if chat_id is None and message.chat and message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id

    st = get_global_stats(chat_id=chat_id, days=days, top_n=10)

    scope = f"чат {st.chat_id}" if st.chat_id else "все чаты"
    period = f"{st.from_dt.date()} → {st.to_dt.date()}"

    lines = [
        f"📊 **Общая статистика**",
        f"🗓 Период: {period} • {scope}",
        "",
        f"💬 Сообщений: **{st.total_messages}**",
        f"👥 Уникальных пользователей: **{st.unique_users}**",
        f"↩️ Реплаев всего: **{st.replies_total}**",
        f"🧩 Стикеров: **{st.stickers_total}** • 🖼 Медиа: **{st.media_total}**",
        "",
    ]

    if st.top_users:
        lines.append("🏆 **Топ авторов:**")
        for i, (tg_id, cnt) in enumerate(st.top_users, start=1):
            lines.append(f"{i}. `{tg_id}` — **{cnt}**")
    else:
        lines.append("🏆 Топ авторов: —")

    await message.answer("\n".join(lines), parse_mode="Markdown")

    if st.activity_daily:
        png = render_activity_plot_png(
            st.activity_daily,
            title=f"Активность: {scope} ({days}д)"
        )
        await message.answer_photo(
            BufferedInputFile(png, filename="activity_global.png"),
            caption="📈 Активность по дням"
        )
