"""Команды для админов: /admin_status, /backfill."""
import asyncio
import html
from datetime import datetime

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from common.logger.logger import get_logger
from services.admin_service import is_admin_tg_id
from services.admin_status_service import (
    fmt_bytes,
    fmt_gap,
    gather_status,
)
from services.backfill_runner import (
    JOB_REGISTRY,
    all_jobs,
    get_job,
    start_job,
    stop_job,
)

router = Router()
logger = get_logger(__name__)


def _require_admin(msg: types.Message) -> bool:
    return bool(msg.from_user and is_admin_tg_id(msg.from_user.id))


async def _send_mono(msg: types.Message, text: str):
    safe = html.escape(text)
    await msg.answer(f"<pre>{safe}</pre>", parse_mode="HTML")


async def _edit_mono(message: types.Message, text: str):
    safe = html.escape(text)
    try:
        await message.edit_text(f"<pre>{safe}</pre>", parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


def _format_status(data: dict) -> str:
    lines = ["Состояние бота", ""]

    build = data["build"]
    lines.append(f"Версия:  {build['sha']} ({build['time']})")
    lines.append(f"Uptime:  {data['uptime']}")
    lines.append(f"Модель:  {data['model']}")
    lines.append("")

    lines.append("[Сервисы]")
    for name, s in data["services"].items():
        if s.get("ok"):
            lines.append(f"  [ok]   {name:<10} {s['latency_ms']}ms")
        else:
            err = s.get("error", "?")
            lines.append(f"  [fail] {name:<10} {err}")
    lines.append("")

    lines.append("[Покрытие данных] (топ-10 чатов)")
    for c in data["coverage"]:
        total = c["total"]
        emb = c["emb_done"]
        nlp = c["nlp_done"]
        eligible = c["eligible_emb"]
        emb_pct = (emb / eligible * 100) if eligible else 0
        nlp_pct = (nlp / total * 100) if total else 0
        gap_emb = fmt_gap(c["latest_msg"], c["latest_emb"])
        gap_nlp = fmt_gap(c["latest_msg"], c["latest_nlp"])
        lines.append(f"  chat {c['chat_id']}  ({total} msg)")
        lines.append(f"    emb: {emb}/{eligible} ({emb_pct:.1f}%, gap {gap_emb})")
        lines.append(f"    nlp: {nlp}/{total} ({nlp_pct:.1f}%, gap {gap_nlp})")
    lines.append("")

    lines.append("[Планировщик]")
    if data["scheduler"]:
        for j in data["scheduler"]:
            next_r = j["next_run"].strftime("%Y-%m-%d %H:%M:%S") if j["next_run"] else "—"
            lines.append(f"  {j['id']:<24} next: {next_r}")
    else:
        lines.append("  (нет активных задач)")
    lines.append("")

    lines.append("[Backfill jobs]")
    jobs = all_jobs()
    if not jobs:
        lines.append("  (не запускались)")
    else:
        for name, j in jobs.items():
            state = "RUNNING" if j.is_running else "done"
            elapsed = ""
            if j.started_at:
                end = j.finished_at or datetime.utcnow()
                elapsed = f" (за {int((end - j.started_at).total_seconds())}с)"
            lines.append(f"  {name:<10} {state}  processed={j.processed} rate={j.rate_per_sec:.1f}/s{elapsed}")
    lines.append("")

    lines.append("[Топ таблиц по размеру]")
    for t in data["tables"]:
        lines.append(f"  {t['name']:<28} {fmt_bytes(t['size_bytes']):>10} ({t['rows']} rows)")

    return "\n".join(lines)


@router.message(Command("admin_status"))
async def cmd_admin_status(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Только для админов бота.")
        return
    progress = await msg.answer("Собираю статус…")
    try:
        data = await gather_status()
        text = _format_status(data)
        await _edit_mono(progress, text)
    except Exception as exc:
        logger.exception("admin_status failed")
        await progress.edit_text(f"Ошибка: {exc}")


# ---------------- /backfill ----------------


HELP_TEXT = (
    "Использование:\n"
    "  /backfill list                — показать состояние\n"
    f"  /backfill start <{ '|'.join(JOB_REGISTRY)}>   — запустить\n"
    "  /backfill stop <name>         — остановить\n"
)


@router.message(Command("backfill"))
async def cmd_backfill(msg: types.Message):
    if not _require_admin(msg):
        await msg.answer("Только для админов бота.")
        return

    parts = (msg.text or "").split()
    if len(parts) < 2:
        await _send_mono(msg, HELP_TEXT)
        return

    sub = parts[1].lower()
    if sub in ("list", "status"):
        await _backfill_list(msg)
        return
    if sub == "start":
        if len(parts) < 3:
            await msg.answer("Укажи имя: /backfill start embed | nlp")
            return
        name = parts[2].lower()
        started, info = start_job(name)
        prefix = "[started]" if started else "[skip]"
        await msg.answer(f"{prefix} backfill `{name}`: {info}", parse_mode="Markdown")
        if started:
            asyncio.create_task(_monitor_job_progress(msg, name))
        return
    if sub == "stop":
        if len(parts) < 3:
            await msg.answer("Укажи имя: /backfill stop embed | nlp")
            return
        name = parts[2].lower()
        ok = stop_job(name)
        await msg.answer(("[stopped] " if ok else "[skip] ") + f"stop {name}: {'ok' if ok else 'не был запущен'}")
        return

    await _send_mono(msg, HELP_TEXT)


async def _backfill_list(msg: types.Message):
    jobs = all_jobs()
    if not jobs:
        await msg.answer("Backfill jobs ещё не запускались.")
        return
    lines = ["Backfill jobs", ""]
    for name, j in jobs.items():
        state = "RUNNING" if j.is_running else "done"
        elapsed_s = 0
        if j.started_at:
            end = j.finished_at or datetime.utcnow()
            elapsed_s = int((end - j.started_at).total_seconds())
        line = (
            f"{name:<10} {state}  processed={j.processed}  rate={j.rate_per_sec:.1f}/s  elapsed={elapsed_s}s"
        )
        if j.last_error:
            line += f"\n  last_error: {j.last_error[:120]}"
        lines.append(line)
    await _send_mono(msg, "\n".join(lines))


async def _monitor_job_progress(msg: types.Message, name: str):
    """Периодически постит апдейт прогресса в чат, пока job не закончится."""
    job = get_job(name)
    if job is None:
        return
    last_processed = -1
    progress_msg = await msg.answer(f"backfill `{name}` запущен…", parse_mode="Markdown")
    while job.is_running:
        await asyncio.sleep(15)
        if job.processed == last_processed:
            continue
        last_processed = job.processed
        text = (
            f"backfill {name}: processed={job.processed} "
            f"rate={job.rate_per_sec:.1f}/s "
            f"elapsed={int((datetime.utcnow() - job.started_at).total_seconds())}s"
        )
        try:
            await _edit_mono(progress_msg, text)
        except Exception:
            logger.exception("backfill monitor edit failed")
            break
    # финальный апдейт
    final = (
        f"backfill {name} завершён\n"
        f"processed={job.processed} rate={job.rate_per_sec:.1f}/s "
        f"elapsed={int((job.finished_at - job.started_at).total_seconds()) if job.finished_at and job.started_at else 0}s"
    )
    if job.last_error:
        final += f"\nlast_error: {job.last_error[:200]}"
    try:
        await _edit_mono(progress_msg, final)
    except Exception:
        pass
