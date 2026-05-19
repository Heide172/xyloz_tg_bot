"""FastAPI backend для Telegram Mini App.

Auth: Telegram WebApp initData HMAC через TELEGRAM_TOKEN.
Reuses bot/services через PYTHONPATH=/app:/app/bot.
"""
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Reuse services из bot/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from api.routes import admin as admin_routes
from api.routes import clicker as clicker_routes
from api.routes import economy as economy_routes
from api.routes import games as games_routes
from api.routes import history as history_routes
from api.routes import duel as duel_routes
from api.routes import gacha as gacha_routes
from api.routes import feedback as feedback_routes
from api.routes import tags as tags_routes
from api.routes import social as social_routes
from api.routes import stats as stats_routes
from api.routes import markets as markets_routes
from api.routes import portfolio as portfolio_routes
from api.routes import events as events_routes
from api.routes import analytics as analytics_routes

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

ALLOWED_ORIGINS = [
    o.strip() for o in (os.getenv("API_CORS_ORIGINS") or "*").split(",") if o.strip()
]

app = FastAPI(title="xyloz-bot-api", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


_pool_last = [0.0]


@app.middleware("http")
async def _perf_mw(request, call_next):
    import time as _t

    t0 = _t.perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        dur_ms = (_t.perf_counter() - t0) * 1000.0
        try:
            from common.metrics import record_pool, record_request

            r = request.scope.get("route")
            route = getattr(r, "path", None) or request.url.path
            record_request(route, request.method, status, dur_ms)
            now = _t.time()
            if now - _pool_last[0] > 2:  # пул пишем не чаще раза в 2с/воркер
                _pool_last[0] = now
                from common.db.db import engine

                pl = engine.pool
                record_pool(
                    os.getpid(),
                    getattr(pl, "size", lambda: 0)(),
                    getattr(pl, "checkedout", lambda: 0)(),
                    getattr(pl, "overflow", lambda: 0)(),
                )
        except Exception:
            pass


@app.get("/")
def root() -> dict:
    return {"service": app.title, "version": app.version, "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


app.include_router(economy_routes.router, prefix="/api/v1", tags=["economy"])
app.include_router(markets_routes.router, prefix="/api/v1/markets", tags=["markets"])
app.include_router(portfolio_routes.router, prefix="/api/v1/portfolio", tags=["portfolio"])
app.include_router(games_routes.router, prefix="/api/v1/games", tags=["games"])
app.include_router(admin_routes.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(clicker_routes.router, prefix="/api/v1/farm", tags=["clicker"])
app.include_router(history_routes.router, prefix="/api/v1/history", tags=["history"])
app.include_router(stats_routes.router, prefix="/api/v1/stats", tags=["stats"])
app.include_router(social_routes.router, prefix="/api/v1/social", tags=["social"])
app.include_router(duel_routes.router, prefix="/api/v1/duel", tags=["duel"])
app.include_router(tags_routes.router, prefix="/api/v1/tags", tags=["tags"])
app.include_router(gacha_routes.router, prefix="/api/v1/gacha", tags=["gacha"])
app.include_router(feedback_routes.router, prefix="/api/v1/feedback", tags=["feedback"])
app.include_router(events_routes.router, prefix="/api/v1", tags=["events"])
app.include_router(analytics_routes.router, prefix="/api/v1", tags=["analytics"])
