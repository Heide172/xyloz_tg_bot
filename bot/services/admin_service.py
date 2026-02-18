import os


def get_admin_ids() -> set[int]:
    raw = os.getenv("BOT_ADMIN_IDS", "")
    ids: set[int] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            continue
    return ids


def is_admin_tg_id(tg_id: int) -> bool:
    return tg_id in get_admin_ids()
