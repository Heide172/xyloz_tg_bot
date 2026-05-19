"""Модерация обратной связи + награда автору за закрытый баг/идею.

Награда — это эмиссия (mint, как clicker/start_bonus): начисляется на
баланс автора в чате, откуда фидбэк отправлен. Банк чата не трогаем.
"""
import os
from datetime import datetime

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.feedback import Feedback
from common.models.user import User
from services.markets_service import _get_or_create_balance, _log_tx

logger = get_logger(__name__)

REWARD_BUG = int(os.getenv("FEEDBACK_REWARD_BUG", "500"))
REWARD_IDEA = int(os.getenv("FEEDBACK_REWARD_IDEA", "300"))


def default_reward(kind: str) -> int:
    return REWARD_BUG if kind == "bug" else REWARD_IDEA


def _admin_tg_ids() -> list[int]:
    out = []
    for part in (os.getenv("BOT_ADMIN_IDS") or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            pass
    return out


def create_feedback(
    user_id: int | None, chat_id, kind: str, text: str, who: str
) -> int:
    """Создать заявку + уведомить админов в ЛС. Возвращает id."""
    if kind not in ("bug", "idea"):
        kind = "idea"
    text = (text or "").strip()[:2000]
    session = SessionLocal()
    try:
        fb = Feedback(
            user_id=user_id, chat_id=chat_id, kind=kind, text=text,
            status="new", created_at=datetime.utcnow(),
        )
        session.add(fb)
        session.commit()
        fid = fb.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    from services.social_service import send_chat_message

    icon = "🐞 Баг" if kind == "bug" else "💡 Идея"
    note = f"{icon} #{fid} от {who} (через ИИ-форму):\n\n{text}"
    for admin_id in _admin_tg_ids():
        try:
            send_chat_message(admin_id, note)
        except Exception:
            logger.warning("feedback notify failed for admin %s", admin_id)
    return fid


def list_open(limit: int = 20) -> list[dict]:
    """Незакрытые заявки (new|seen), новые сверху."""
    session = SessionLocal()
    try:
        rows = (
            session.query(Feedback)
            .filter(Feedback.status != "done")
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "text": r.text,
                "chat_id": r.chat_id,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        session.close()


def get_one(fid: int) -> dict | None:
    session = SessionLocal()
    try:
        r = session.query(Feedback).filter(Feedback.id == fid).first()
        if not r:
            return None
        return {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "text": r.text,
            "chat_id": r.chat_id,
            "reward": r.reward,
            "created_at": r.created_at,
        }
    finally:
        session.close()


def close(fid: int, amount: int | None = None) -> dict:
    """Закрыть заявку и (опц.) наградить автора. Идемпотентно.

    amount=None → дефолт по типу; amount=0 → закрыть без награды.
    Возвращает dict со статусом операции для уведомления автора.
    """
    session = SessionLocal()
    try:
        fb = (
            session.query(Feedback)
            .filter(Feedback.id == fid)
            .with_for_update()
            .first()
        )
        if not fb:
            return {"ok": False, "error": "not_found"}
        if fb.status == "done":
            return {
                "ok": False,
                "error": "already_done",
                "reward": fb.reward,
                "kind": fb.kind,
            }

        reward = default_reward(fb.kind) if amount is None else max(0, amount)
        now = datetime.utcnow()

        author_tg_id = None
        author_name = None
        if fb.user_id is not None:
            u = session.query(User).filter(User.id == fb.user_id).first()
            if u:
                author_tg_id = u.tg_id
                author_name = ("@" + u.username) if u.username else (
                    u.fullname or f"id{u.tg_id}"
                )

        credited = False
        if reward > 0 and fb.chat_id is not None and fb.user_id is not None:
            bal = _get_or_create_balance(session, fb.user_id, fb.chat_id)
            bal.balance += reward
            bal.updated_at = now
            _log_tx(
                session, fb.user_id, fb.chat_id, reward,
                kind="feedback_reward", ref_id=str(fb.id),
                note=f"{fb.kind} #{fb.id}",
            )
            credited = True
        elif reward > 0:
            # Нет чата/автора — наградить некуда; закрываем без выплаты.
            reward = 0

        fb.status = "done"
        fb.reward = reward
        fb.rewarded_at = now if credited else None
        session.commit()

        return {
            "ok": True,
            "id": fid,
            "kind": fb.kind,
            "reward": reward,
            "credited": credited,
            "chat_id": fb.chat_id,
            "author_tg_id": author_tg_id,
            "author_name": author_name,
            "text": fb.text,
        }
    except Exception:
        session.rollback()
        logger.exception("feedback close failed id=%s", fid)
        return {"ok": False, "error": "internal"}
    finally:
        session.close()
