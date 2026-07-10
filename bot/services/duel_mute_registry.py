"""Реестр дуэль-мутов и очередь тегов — единый источник правды «кто в муте до
какого времени» и «какой тег ждёт применения после мута».

Живёт на BotSetting (БД), БЕЗ aiogram — читается и из процесса бота, и из API
(аренда тегов). Ключи:
  duelmute:{chat}:{tg}   -> JSON {until, kind, title?, rights?}
  pendingtag:{chat}:{tg} -> строка custom_title, отложенного из-за мута

Зачем: выдача тега = promoteChatMember, а Telegram снимает restrict с админа.
Чтобы тег не сбивал мут, при активном муте тег кладём в очередь и вешаем
после (см. tag_service.process_expired_duel_mutes)."""
import json
import time

from common.db.db import SessionLocal, engine
from common.logger.logger import get_logger
from common.models.bot_setting import BotSetting

logger = get_logger(__name__)

_MUTE = "duelmute:"
_PENDING = "pendingtag:"


def _ensure_table() -> None:
    BotSetting.__table__.create(bind=engine, checkfirst=True)


def _get(key: str) -> str | None:
    _ensure_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == key).first()
        return row.value if row else None
    finally:
        s.close()


def _set(key: str, value: str) -> None:
    _ensure_table()
    s = SessionLocal()
    try:
        row = s.query(BotSetting).filter(BotSetting.key == key).first()
        if row:
            row.value = value
        else:
            s.add(BotSetting(key=key, value=value))
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _delete(key: str) -> None:
    _ensure_table()
    s = SessionLocal()
    try:
        s.query(BotSetting).filter(BotSetting.key == key).delete()
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _with_prefix(prefix: str) -> list[tuple[str, str]]:
    _ensure_table()
    s = SessionLocal()
    try:
        rows = s.query(BotSetting).filter(BotSetting.key.like(prefix + "%")).all()
        return [(r.key, r.value) for r in rows]
    finally:
        s.close()


# ---------------- мут ----------------


def set_mute(
    chat_id: int,
    tg_id: int,
    until_epoch: int,
    kind: str,
    title: str | None = None,
    rights: dict | None = None,
) -> None:
    """kind: 'native' | 'hard_admin' | 'soft'. title/rights нужны только для
    hard_admin (вернуть после мута)."""
    payload: dict = {"until": int(until_epoch), "kind": kind}
    if title:
        payload["title"] = title
    if rights:
        payload["rights"] = rights
    _set(f"{_MUTE}{chat_id}:{tg_id}", json.dumps(payload))


def _parse_mute(raw: str) -> dict | None:
    try:
        d = json.loads(raw)
        return {
            "until": int(d["until"]),
            "kind": d.get("kind", "hard_admin"),  # старый JSON без kind = тег-админ
            "title": d.get("title") or "",
            "rights": d.get("rights") or {},
        }
    except (ValueError, KeyError, TypeError):
        # старейший формат 'until:title'
        epoch, _, title = raw.partition(":")
        try:
            return {"until": int(epoch), "kind": "hard_admin", "title": title,
                    "rights": {"can_invite_users": True}}
        except ValueError:
            return None


def get_mute(chat_id: int, tg_id: int) -> dict | None:
    raw = _get(f"{_MUTE}{chat_id}:{tg_id}")
    return _parse_mute(raw) if raw else None


def muted_until(chat_id: int, tg_id: int) -> int | None:
    m = get_mute(chat_id, tg_id)
    return m["until"] if m else None


def is_muted_now(chat_id: int, tg_id: int) -> bool:
    u = muted_until(chat_id, tg_id)
    return u is not None and u > int(time.time())


def clear_mute(chat_id: int, tg_id: int) -> None:
    _delete(f"{_MUTE}{chat_id}:{tg_id}")


def iter_mutes() -> list[tuple[int, int, dict]]:
    """(chat_id, tg_id, mute) по всем записям; битые ключи вычищает."""
    out: list[tuple[int, int, dict]] = []
    for key, value in _with_prefix(_MUTE):
        parts = key.split(":")
        if len(parts) != 3:
            _delete(key)
            continue
        try:
            chat_id, tg_id = int(parts[1]), int(parts[2])
        except ValueError:
            _delete(key)
            continue
        mute = _parse_mute(value)
        if mute is None:
            _delete(key)
            continue
        out.append((chat_id, tg_id, mute))
    return out


# ---------------- очередь тегов ----------------


def queue_tag(chat_id: int, tg_id: int, title: str) -> None:
    _set(f"{_PENDING}{chat_id}:{tg_id}", title or "")


def pending_tag(chat_id: int, tg_id: int) -> str | None:
    return _get(f"{_PENDING}{chat_id}:{tg_id}")


def clear_pending_tag(chat_id: int, tg_id: int) -> None:
    _delete(f"{_PENDING}{chat_id}:{tg_id}")
