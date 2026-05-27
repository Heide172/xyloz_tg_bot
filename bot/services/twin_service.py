"""«Двойник дня» — выбор таргета и расчёт его поведенческого профиля.

Этап 1 MVP: только pick + persona stats + scheduler-job-хук. Без listener,
без LLM, без оплаты — это придёт в этапах 2-4.

Логика выбора:
  1. Берём participant_of_day из daily_picks за вчера (это и есть «активный
     участник дня», который daily_nominations выбрал утром).
  2. Резолвим tg_id → users.id, проверяем opt-out (twin_consent.enabled=false → пропуск).
  3. Проверяем минимум сообщений (TWIN_MIN_CORPUS, default 30) в этом чате
     за последние 30 дней — без корпуса имитировать нечего.
  4. Если первый кандидат не прошёл — берём следующих winner-ов из daily_picks
     за последние 7 дней.
  5. Если никого — двойника на сегодня нет (state.target_user_id = None).
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text as sa_text

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.chat_twin_state import ChatTwinState
from common.models.message import Message
from common.models.twin_consent import TwinConsent
from common.models.user import User

logger = get_logger(__name__)

MSK = ZoneInfo("Europe/Moscow")
MIN_CORPUS = int(os.getenv("TWIN_MIN_CORPUS", "30"))
PERSONA_WINDOW_DAYS = int(os.getenv("TWIN_PERSONA_WINDOW_DAYS", "30"))
FALLBACK_LOOKBACK_DAYS = int(os.getenv("TWIN_FALLBACK_LOOKBACK_DAYS", "7"))


def _today_msk_date():
    return datetime.now(tz=MSK).date()


def _yesterday_msk_date():
    return _today_msk_date() - timedelta(days=1)


def compute_persona_stats(
    user_id: int, chat_id: int, days: int = PERSONA_WINDOW_DAYS
) -> dict:
    """Считает поведенческий профиль таргета для адаптивного pacing.

    avg_msg_len      — среднее длины символов
    avg_reply_rate   — доля сообщений с reply_to
    avg_response_lag — медиана секунд между триггер-сообщением и его reply
    active_hours_msk — топ-3 часов активности (по UTC сдвигаем в MSK)
    msg_count        — объём корпуса в окне
    """
    session = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(
                Message.id,
                Message.text,
                Message.reply_to,
                Message.created_at,
            )
            .filter(
                Message.user_id == user_id,
                Message.chat_id == chat_id,
                Message.created_at >= since,
                Message.text.isnot(None),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        msg_count = len(rows)
        if msg_count == 0:
            return {
                "msg_count": 0,
                "avg_msg_len": 0,
                "avg_reply_rate": 0.0,
                "avg_response_lag": 30,
                "active_hours_msk": [],
            }
        total_len = sum(len(r.text or "") for r in rows)
        avg_len = round(total_len / msg_count, 1)
        reply_count = sum(1 for r in rows if r.reply_to)
        avg_reply_rate = round(reply_count / msg_count, 3)

        # response lag: для каждого reply-сообщения смотрим created_at
        # триггер-сообщения через JOIN. Делаем raw SQL — иначе много трипов.
        lag_rows = session.execute(sa_text("""
            SELECT EXTRACT(EPOCH FROM (m.created_at - t.created_at)) AS lag_s
            FROM messages m
            JOIN messages t ON t.chat_id = m.chat_id
                           AND t.telegram_message_id = m.reply_to
            WHERE m.user_id = :uid
              AND m.chat_id = :cid
              AND m.created_at >= :since
              AND m.reply_to IS NOT NULL
        """), {"uid": user_id, "cid": chat_id, "since": since}).fetchall()
        lags = sorted(int(r[0]) for r in lag_rows if r[0] and 0 < r[0] < 6 * 3600)
        avg_lag = lags[len(lags) // 2] if lags else 30

        # hours: переводим UTC → MSK
        hour_counts: dict[int, int] = {}
        for r in rows:
            if not r.created_at:
                continue
            h = (r.created_at.hour + 3) % 24  # naive UTC + MSK offset
            hour_counts[h] = hour_counts.get(h, 0) + 1
        top_hours = sorted(hour_counts.items(), key=lambda x: -x[1])[:3]

        return {
            "msg_count": msg_count,
            "avg_msg_len": avg_len,
            "avg_reply_rate": avg_reply_rate,
            "avg_response_lag": avg_lag,
            "active_hours_msk": [h for h, _ in top_hours],
        }
    finally:
        session.close()


def _has_min_corpus(session, user_id: int, chat_id: int) -> bool:
    cnt = session.execute(sa_text(
        "SELECT COUNT(*) FROM messages WHERE user_id=:u AND chat_id=:c "
        "AND created_at >= :s AND text IS NOT NULL"
    ), {
        "u": user_id, "c": chat_id,
        "s": datetime.utcnow() - timedelta(days=PERSONA_WINDOW_DAYS),
    }).scalar() or 0
    return cnt >= MIN_CORPUS


def _opted_out(session, user_id: int) -> bool:
    row = session.query(TwinConsent).filter(TwinConsent.user_id == user_id).first()
    if not row:
        return False  # дефолт = участвует
    return not row.enabled


def _candidate_user_ids(session, chat_id: int) -> list[tuple[int, int, str]]:
    """Возвращает [(user_id, tg_id, name), ...] кандидатов в порядке приоритета:
    сегодняшний participant_of_day (тот, у кого сейчас висит тег «пидор дня»)
    → вчерашний → ещё ранее за 7 дней. pick_participant_of_day сохраняет
    запись с day_msk = today; daily_nominations крутится в 10:00 MSK, наш
    twin-rotate — в 10:10, так что к этому моменту запись на сегодня уже
    есть. Если нет (бот стартанул раньше) — берём вчерашнего как фолбэк.
    """
    today = _today_msk_date()
    lookback = today - timedelta(days=FALLBACK_LOOKBACK_DAYS)
    rows = session.execute(sa_text("""
        SELECT DISTINCT ON (winner_tg_id) day_msk, winner_tg_id
        FROM daily_picks
        WHERE chat_id = :c AND day_msk BETWEEN :from_d AND :to_d
          AND title = 'participant_of_day'
        ORDER BY winner_tg_id, day_msk DESC
    """), {"c": chat_id, "from_d": lookback, "to_d": today}).fetchall()
    # сортируем по дате (свежие первыми) — порядок приоритета:
    # сегодняшний пидор дня впереди.
    rows = sorted(rows, key=lambda r: r[0], reverse=True)
    out = []
    for _day, tg_id in rows:
        u = session.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            continue
        out.append((int(u.id), int(u.tg_id), u.username or u.fullname or f"id{u.tg_id}"))
    return out


def pick_target_for_day(chat_id: int) -> dict | None:
    """Подобрать таргета на сегодня. Возвращает {target_user_id, target_tg_id,
    target_name, day_msk, persona_stats} или None если никто не подошёл.
    """
    session = SessionLocal()
    try:
        candidates = _candidate_user_ids(session, chat_id)
        for user_id, tg_id, name in candidates:
            if _opted_out(session, user_id):
                logger.info("twin pick: skip opt-out user=%s chat=%s", user_id, chat_id)
                continue
            if not _has_min_corpus(session, user_id, chat_id):
                logger.info(
                    "twin pick: skip thin corpus user=%s chat=%s", user_id, chat_id
                )
                continue
            stats = compute_persona_stats(user_id, chat_id)
            return {
                "target_user_id": user_id,
                "target_tg_id": tg_id,
                "target_name": name,
                "day_msk": _today_msk_date(),
                "persona_stats": stats,
            }
        return None
    finally:
        session.close()


def set_target_for_day(chat_id: int, target: dict | None) -> None:
    """Upsert chat_twin_state. None — сбросить таргета (state.enabled остаётся)."""
    session = SessionLocal()
    try:
        state = (
            session.query(ChatTwinState)
            .filter(ChatTwinState.chat_id == chat_id)
            .with_for_update()
            .first()
        )
        if state is None:
            state = ChatTwinState(chat_id=chat_id, enabled=True)
            session.add(state)
        if target:
            state.target_user_id = target["target_user_id"]
            state.target_tg_id = target["target_tg_id"]
            state.target_name = target["target_name"]
            state.day_msk = target["day_msk"]
            state.persona_stats = target["persona_stats"]
        else:
            state.target_user_id = None
            state.target_tg_id = None
            state.target_name = None
            state.day_msk = _today_msk_date()
            state.persona_stats = None
        state.replies_today = 0
        state.last_reply_at = None
        state.updated_at = datetime.utcnow()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def rotate_daily(chat_ids: list[int]) -> dict:
    """Точка входа для scheduler-job. Возвращает summary для лога."""
    picked = 0
    empty = 0
    for cid in chat_ids:
        try:
            target = pick_target_for_day(cid)
            set_target_for_day(cid, target)
            if target:
                picked += 1
                logger.info(
                    "twin rotated chat=%s → %s (corpus=%d, lag=%ss)",
                    cid, target["target_name"],
                    target["persona_stats"]["msg_count"],
                    target["persona_stats"]["avg_response_lag"],
                )
            else:
                empty += 1
                logger.info("twin rotated chat=%s → нет валидных кандидатов", cid)
        except Exception:
            logger.exception("twin rotate failed for chat=%s", cid)
    return {"picked": picked, "empty": empty}


def set_target_by_identifier(chat_id: int, identifier: str) -> dict | None:
    """Принудительно поставить таргета по @username или tg_id (для теста / админа).
    Возвращает target dict или None если юзер не найден / нет корпуса.
    """
    identifier = (identifier or "").strip().lstrip("@")
    session = SessionLocal()
    try:
        u = None
        try:
            tg_id = int(identifier)
            u = session.query(User).filter(User.tg_id == tg_id).first()
        except ValueError:
            u = session.query(User).filter(User.username == identifier).first()
        if u is None:
            return None
        if not _has_min_corpus(session, u.id, chat_id):
            logger.info(
                "twin set_target: thin corpus user=%s chat=%s", u.id, chat_id
            )
            return None
        stats = compute_persona_stats(int(u.id), chat_id)
        target = {
            "target_user_id": int(u.id),
            "target_tg_id": int(u.tg_id),
            "target_name": u.username or u.fullname or f"id{u.tg_id}",
            "day_msk": _today_msk_date(),
            "persona_stats": stats,
        }
    finally:
        session.close()
    set_target_for_day(chat_id, target)
    return target


def get_state(chat_id: int) -> dict | None:
    """Безопасный read-only снапшот состояния для listener/UI."""
    session = SessionLocal()
    try:
        s = session.query(ChatTwinState).filter(ChatTwinState.chat_id == chat_id).first()
        if not s:
            return None
        return {
            "chat_id": s.chat_id,
            "target_user_id": s.target_user_id,
            "target_tg_id": s.target_tg_id,
            "target_name": s.target_name,
            "day_msk": s.day_msk.isoformat() if s.day_msk else None,
            "enabled": s.enabled,
            "paused_until": s.paused_until.isoformat() if s.paused_until else None,
            "replies_today": s.replies_today,
            "last_reply_at": s.last_reply_at.isoformat() if s.last_reply_at else None,
            "persona_stats": s.persona_stats or {},
        }
    finally:
        session.close()
