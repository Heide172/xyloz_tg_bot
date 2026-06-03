"""Настройки vpn-digest из env. Переиспользует TG_API_ID/TG_API_HASH из xyloz."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Локально подхватываем .env из корня проекта (в контейнере переменные уже в окружении,
# load_dotenv их не перезатирает).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


def _csv(name: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, "").split(",") if p.strip()]


def monitored_chat_ids() -> list[int | str]:
    """VPN_MONITORED_CHAT_IDS: csv из chat_id (-100...) или username (@chat)."""
    out: list[int | str] = []
    for p in _csv("VPN_MONITORED_CHAT_IDS"):
        try:
            out.append(int(p))
        except ValueError:
            out.append(p)
    return out


# --- Telegram userbot (общие с history_load имена) ---
TG_API_ID = int(os.getenv("TG_API_ID", "0") or "0")
TG_API_HASH = os.getenv("TG_API_HASH", "")
# Строковая сессия для контейнера (генерится `python -m vpndigest.login`).
VPN_SESSION_STRING = os.getenv("VPN_SESSION_STRING", "")

MONITORED_CHAT_IDS = monitored_chat_ids()

# --- Доставка (тем же юзер-аккаунтом) ---
# Пусто/пробелы/не задано -> "me" (Saved Messages). Гарантия: без явного
# валидного значения дайджест уходит ТОЛЬКО в Избранное, никуда наружу.
VPN_DIGEST_TARGET_CHAT = (os.getenv("VPN_DIGEST_TARGET_CHAT") or "").strip() or "me"

# --- Backfill ---
VPN_BACKFILL_DAYS = int(os.getenv("VPN_BACKFILL_DAYS", "7"))

# --- LLM (через bot.services.ai_client / OpenCode) ---
VPN_DIGEST_MODEL = os.getenv("VPN_DIGEST_MODEL", "opencode-go/qwen3.5-plus")

# --- Расписание ---
VPN_DIGEST_CRON = os.getenv("VPN_DIGEST_CRON", "0 9 * * *")
VPN_DIGEST_WINDOW_HOURS = int(os.getenv("VPN_DIGEST_WINDOW_HOURS", "24"))
VPN_TZ = os.getenv("TZ", "Europe/Moscow")
