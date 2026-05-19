"""ИИ-форма обратной связи: отвечает на вопрос и сам заводит заявку.

v1: один заход (без истории). Строгий JSON от модели:
{"reply": "...", "register": {"kind":"bug|idea","text":"..."} | null}
Авто-регистрация + прозрачно сообщаем «завёл заявку #N».
Любой сбой/непарс → деградируем (reply + register=null), фронт
покажет фолбэк-форму.
"""
import json
import re

from common.logger.logger import get_logger
from services import ai_client
from services.feedback_service import create_feedback
from services.summary_service import get_summary_model

logger = get_logger(__name__)

# Грунтинг: краткие возможности «Бурмалды», чтобы ИИ не галлюцинировал.
_FEATURES = (
    "Это Telegram-бот и Mini App «Бурмалда» (чат-экономика на гривнах). "
    "Возможности: Ферма (тапаешь, копишь cp, продаёшь на AMM-рынок — "
    "курс живой, чем больше продаёшь за раз тем хуже цена, со временем "
    "восстанавливается; есть график курса, кривая price-impact, лестница "
    "котировок); Гача (крутки персонажей); Рынки (parimutuel-ставки); "
    "Игры (blackjack, slots, рулетка, дайс); Магазин (прожарка/анекдот/"
    "пнуть); Дуэли 1v1; Аренда тегов-подписей; Переводы (комиссия 5%); "
    "Номинации дня и «пидор дня» с наградами; раздел «Что нового». "
    "Баланс обновляется вживую. Команда /casino открывает Mini App."
)

_SYSTEM = (
    "Ты — поддержка Mini App «Бурмалда». Отвечай по-русски, кратко и "
    "по делу, только про этот продукт (контекст ниже). Если не знаешь — "
    "честно скажи и предложи оставить заявку.\n\n"
    f"КОНТЕКСТ:\n{_FEATURES}\n\n"
    "Если сообщение — это баг (что-то сломалось) или конкретная идея/"
    "пожелание, заведи заявку. Просто вопрос — отвечай, register=null.\n"
    "Верни СТРОГО валидный JSON без markdown, без текста вокруг:\n"
    '{"reply": "ответ юзеру", "register": {"kind": "bug|idea", '
    '"text": "чистая формулировка заявки"} } '
    "или с \"register\": null. Ничего кроме JSON."
)


def _parse(raw: str) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.I).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def assist(user_id: int | None, chat_id, who: str, message: str) -> dict:
    msg = (message or "").strip()[:2000]
    if len(msg) < 2:
        return {"reply": "Опиши вопрос или проблему подробнее.",
                "registered": None}

    fallback = {
        "reply": "ИИ сейчас недоступен. Можешь отправить заявку напрямую "
                 "кнопкой «Отправить без ИИ».",
        "registered": None,
        "degraded": True,
    }
    try:
        raw = ai_client.call(msg, get_summary_model(), _SYSTEM)
    except Exception:
        logger.warning("feedback_ai call failed")
        return fallback

    data = _parse(raw)
    if not data or not isinstance(data, dict):
        logger.warning("feedback_ai unparseable: %s", (raw or "")[:200])
        return fallback

    reply = str(data.get("reply") or "").strip() or "Принято."
    reg = data.get("register")
    registered = None
    if isinstance(reg, dict):
        kind = reg.get("kind")
        text = str(reg.get("text") or "").strip()
        if kind in ("bug", "idea") and len(text) >= 5:
            try:
                fid = create_feedback(user_id, chat_id, kind, text, who)
                registered = {"id": fid, "kind": kind}
            except Exception:
                logger.exception("feedback_ai create failed")
    return {"reply": reply, "registered": registered}
