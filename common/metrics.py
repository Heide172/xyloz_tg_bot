"""Лёгкие перф-метрики API в Redis (кросс-воркер).

Best-effort: нет Redis / ошибка → тихо пропускаем, запрос не страдает.
Латентность раскладываем по фикс-бакетам → p50/p95 без зависимостей.
"""
import os
import time

from common.logger.logger import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")
_BUCKETS_MS = [50, 100, 200, 500, 1000, 2000, 5000]  # +inf = последний
_ROUTES_SET = "perf:routes"

_client = None
_init = False


def _redis():
    global _client, _init
    if _init:
        return _client
    _init = True
    if not REDIS_URL:
        return None
    try:
        import redis

        _client = redis.from_url(
            REDIS_URL, socket_timeout=1, socket_connect_timeout=1,
            decode_responses=True,
        )
    except Exception as exc:
        logger.warning("metrics redis init failed: %s", str(exc)[:120])
        _client = None
    return _client


def _bucket(dur_ms: float) -> int:
    for i, edge in enumerate(_BUCKETS_MS):
        if dur_ms < edge:
            return i
    return len(_BUCKETS_MS)  # переполнение = inf-бакет


def record_request(route: str, method: str, status: int, dur_ms: float) -> None:
    """Записать один запрос. Никогда не бросает."""
    cli = _redis()
    if cli is None:
        return
    try:
        key = f"perf:r:{method}:{route}"
        p = cli.pipeline(transaction=False)
        p.sadd(_ROUTES_SET, key)
        p.hincrby(key, "n", 1)
        p.hincrbyfloat(key, "sum", dur_ms)
        if status >= 500:
            p.hincrby(key, "err5", 1)
        elif status >= 400:
            p.hincrby(key, "err4", 1)
        p.hincrby(key, f"b{_bucket(dur_ms)}", 1)
        # max
        p.hget(key, "max")
        res = p.execute()
        cur_max = res[-1]
        if cur_max is None or dur_ms > float(cur_max):
            cli.hset(key, "max", round(dur_ms, 1))
    except Exception:
        pass


def record_pool(pid: int, size: int, checked_out: int, overflow: int) -> None:
    cli = _redis()
    if cli is None:
        return
    try:
        cli.hset("perf:pool", str(pid), f"{checked_out}/{size}+{overflow}")
        cli.expire("perf:pool", 120)
    except Exception:
        pass


def _pctl_from_buckets(buckets: list[int], total: int, q: float) -> str:
    """Грубая оценка перцентиля по бакетам — возвращает «<edge» / «>5000»."""
    if total <= 0:
        return "-"
    target = q * total
    acc = 0
    edges = _BUCKETS_MS + [None]
    for i, c in enumerate(buckets):
        acc += c
        if acc >= target:
            e = edges[i]
            return f"<{e}ms" if e is not None else ">5000ms"
    return ">5000ms"


def snapshot(top: int = 25) -> dict:
    """Сводка для /admin_status и админ-API."""
    cli = _redis()
    if cli is None:
        return {"enabled": False, "routes": [], "pool": {}}
    try:
        keys = list(cli.smembers(_ROUTES_SET))
        rows = []
        for k in keys:
            h = cli.hgetall(k)
            n = int(h.get("n", 0) or 0)
            if n == 0:
                continue
            buckets = [int(h.get(f"b{i}", 0) or 0)
                       for i in range(len(_BUCKETS_MS) + 1)]
            _, method, route = k.split(":", 2)
            rows.append({
                "route": route,
                "method": method,
                "n": n,
                "avg_ms": round(float(h.get("sum", 0) or 0) / n, 1),
                "max_ms": float(h.get("max", 0) or 0),
                "err4": int(h.get("err4", 0) or 0),
                "err5": int(h.get("err5", 0) or 0),
                "p50": _pctl_from_buckets(buckets, n, 0.50),
                "p95": _pctl_from_buckets(buckets, n, 0.95),
            })
        rows.sort(key=lambda r: r["n"], reverse=True)
        pool = cli.hgetall("perf:pool") or {}
        return {"enabled": True, "routes": rows[:top], "pool": pool}
    except Exception as exc:
        logger.warning("metrics snapshot failed: %s", str(exc)[:120])
        return {"enabled": False, "routes": [], "pool": {}}


def reset() -> None:
    cli = _redis()
    if cli is None:
        return
    try:
        keys = list(cli.smembers(_ROUTES_SET))
        if keys:
            cli.delete(*keys)
        cli.delete(_ROUTES_SET, "perf:pool")
    except Exception:
        pass


class _Timer:
    __slots__ = ("t",)

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def ms(self) -> float:
        return (time.perf_counter() - self.t) * 1000.0
