"""Сбор метрик для /admin_status."""
import asyncio
import datetime
import os
import time

import aiohttp
from sqlalchemy import text

from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger

logger = get_logger(__name__)

START_TIME = datetime.datetime.utcnow()


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м {seconds % 60:02d}с"
    if seconds < 86400:
        return f"{seconds // 3600}ч {(seconds % 3600) // 60:02d}м"
    return f"{seconds // 86400}д {(seconds % 86400) // 3600:02d}ч"


def fmt_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_gap(latest_msg, latest_other) -> str:
    if not latest_msg or not latest_other:
        return "—"
    delta = (latest_msg - latest_other).total_seconds()
    if delta <= 0:
        return "0s"
    return _fmt_duration(delta)


def get_uptime_str() -> str:
    elapsed = (datetime.datetime.utcnow() - START_TIME).total_seconds()
    return _fmt_duration(elapsed)


def get_build_info() -> dict:
    return {
        "sha": os.getenv("BUILD_SHA", "—"),
        "time": os.getenv("BUILD_TIME", "—"),
    }


# ---------------- health checks ----------------


def _pg_ping():
    with engine.begin() as c:
        c.exec_driver_sql("SELECT 1")


async def check_postgres() -> dict:
    try:
        start = time.time()
        await asyncio.to_thread(_pg_ping)
        return {"ok": True, "latency_ms": int((time.time() - start) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


async def check_nlp() -> dict:
    url = os.getenv("NLP_SERVICE_URL", "http://nlp:8000").rstrip("/") + "/health"
    try:
        start = time.time()
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
        return {"ok": True, "latency_ms": int((time.time() - start) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


async def check_opencode() -> dict:
    base = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1").rstrip("/")
    api_key = (os.getenv("OPENCODE_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "error": "OPENCODE_API_KEY не задан"}
    try:
        start = time.time()
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{base}/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "xyloz-tg-bot/1.0",
                },
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
        return {"ok": True, "latency_ms": int((time.time() - start) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


# ---------------- DB stats ----------------


def get_coverage_stats() -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.execute(text("""
            SELECT
                m.chat_id,
                COUNT(*) AS total,
                SUM(CASE WHEN length(m.text) >= 10 THEN 1 ELSE 0 END) AS eligible_emb,
                SUM(CASE WHEN m.nlp_processed_at IS NOT NULL THEN 1 ELSE 0 END) AS nlp_done,
                SUM(CASE WHEN e.message_id IS NOT NULL THEN 1 ELSE 0 END) AS emb_done,
                MAX(m.created_at) AS latest_msg,
                MAX(CASE WHEN e.message_id IS NOT NULL THEN m.created_at END) AS latest_emb,
                MAX(CASE WHEN m.nlp_processed_at IS NOT NULL THEN m.created_at END) AS latest_nlp
            FROM messages m
            LEFT JOIN message_embeddings e ON e.message_id = m.id
            WHERE m.text IS NOT NULL AND m.text != ''
            GROUP BY m.chat_id
            ORDER BY total DESC
            LIMIT 10
        """)).all()
        return [
            {
                "chat_id": r.chat_id,
                "total": int(r.total or 0),
                "eligible_emb": int(r.eligible_emb or 0),
                "nlp_done": int(r.nlp_done or 0),
                "emb_done": int(r.emb_done or 0),
                "latest_msg": r.latest_msg,
                "latest_emb": r.latest_emb,
                "latest_nlp": r.latest_nlp,
            }
            for r in rows
        ]
    finally:
        session.close()


def get_table_sizes() -> list[dict]:
    with engine.begin() as c:
        rows = c.exec_driver_sql("""
            SELECT
                C.relname AS table_name,
                pg_total_relation_size(C.oid) AS size_bytes,
                COALESCE(T.n_live_tup, 0) AS row_count
            FROM pg_class C
            LEFT JOIN pg_namespace N ON N.oid = C.relnamespace
            LEFT JOIN pg_stat_user_tables T ON T.relname = C.relname
            WHERE N.nspname = 'public' AND C.relkind = 'r'
            ORDER BY pg_total_relation_size(C.oid) DESC
            LIMIT 8
        """).all()
        return [
            {"name": r[0], "size_bytes": int(r[1] or 0), "rows": int(r[2] or 0)}
            for r in rows
        ]


def get_scheduler_jobs() -> list[dict]:
    from services import scheduler as scheduler_mod
    s = scheduler_mod.get_scheduler()
    if s is None:
        return []
    return [{"id": j.id, "next_run": j.next_run_time} for j in s.get_jobs()]


def get_current_model() -> str:
    try:
        from services.summary_service import get_summary_model
        return get_summary_model()
    except Exception:
        return "—"


# ---------------- aggregator ----------------


async def gather_status() -> dict:
    pg, nlp_st, oc = await asyncio.gather(
        check_postgres(),
        check_nlp(),
        check_opencode(),
    )
    coverage, tables, scheduler_jobs, model = await asyncio.gather(
        asyncio.to_thread(get_coverage_stats),
        asyncio.to_thread(get_table_sizes),
        asyncio.to_thread(get_scheduler_jobs),
        asyncio.to_thread(get_current_model),
    )
    return {
        "build": get_build_info(),
        "uptime": get_uptime_str(),
        "model": model,
        "services": {"postgres": pg, "nlp": nlp_st, "opencode": oc},
        "coverage": coverage,
        "tables": tables,
        "scheduler": scheduler_jobs,
    }
