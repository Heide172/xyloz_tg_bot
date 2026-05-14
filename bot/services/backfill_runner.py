"""Запуск/мониторинг фоновых backfill-задач из бота."""
import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from common.logger.logger import get_logger
from services.embed_worker import embed_pending_once
from services.nlp_classifier import classify_pending_once

logger = get_logger(__name__)


class BackfillJob:
    def __init__(self, name: str, fn: Callable[[], Awaitable[int]]):
        self.name = name
        self.fn = fn
        self.task: asyncio.Task | None = None
        self.processed = 0
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.last_saved: int = 0
        self.idle_iterations: int = 0
        self.stop_requested: bool = False
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def rate_per_sec(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or datetime.utcnow()
        elapsed = (end - self.started_at).total_seconds()
        return self.processed / elapsed if elapsed > 0 else 0.0


JOB_REGISTRY: dict[str, Callable[[], Awaitable[int]]] = {
    "embed": embed_pending_once,
    "nlp": classify_pending_once,
}

_jobs: dict[str, BackfillJob] = {}
SLEEP_AFTER_IDLE_SEC = 5
IDLE_ITERS_BEFORE_STOP = 3


async def _run_loop(job: BackfillJob) -> None:
    job.started_at = datetime.utcnow()
    while not job.stop_requested:
        try:
            saved = await job.fn()
        except Exception as exc:
            job.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("backfill job '%s' iteration failed", job.name)
            await asyncio.sleep(SLEEP_AFTER_IDLE_SEC)
            continue
        if saved > 0:
            job.processed += saved
            job.last_saved = saved
            job.idle_iterations = 0
        else:
            job.idle_iterations += 1
            if job.idle_iterations >= IDLE_ITERS_BEFORE_STOP:
                break
            await asyncio.sleep(SLEEP_AFTER_IDLE_SEC)
    job.finished_at = datetime.utcnow()
    logger.info("backfill job '%s' finished: processed=%d", job.name, job.processed)


def start_job(name: str) -> tuple[bool, str]:
    if name not in JOB_REGISTRY:
        return False, f"unknown job '{name}' (known: {', '.join(JOB_REGISTRY)})"
    existing = _jobs.get(name)
    if existing and existing.is_running:
        return False, "уже запущен"
    job = BackfillJob(name, JOB_REGISTRY[name])
    job.task = asyncio.create_task(_run_loop(job))
    _jobs[name] = job
    return True, "запущен"


def stop_job(name: str) -> bool:
    job = _jobs.get(name)
    if not job or not job.is_running:
        return False
    job.stop_requested = True
    return True


def get_job(name: str) -> BackfillJob | None:
    return _jobs.get(name)


def all_jobs() -> dict[str, BackfillJob]:
    return _jobs
