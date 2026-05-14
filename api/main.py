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
from api.routes import markets as markets_routes
from api.routes import portfolio as portfolio_routes

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
