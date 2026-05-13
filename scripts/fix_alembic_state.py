"""Принудительно ставит alembic_version на текущую head-ревизию.

Используется в одном кейсе: в БД остался ID ревизии, файла которой больше нет
в migrations/versions/ (типичный артефакт прошлых `alembic revision --autogenerate`).

Запуск:
    docker compose run --rm --no-deps bot python scripts/fix_alembic_state.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

from common.db.db import engine

HEAD_REVISION = "20260513_01"


def main() -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        conn.exec_driver_sql("DELETE FROM alembic_version")
        conn.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (%s)",
            (HEAD_REVISION,),
        )
    print(f"alembic_version reset to {HEAD_REVISION}")


if __name__ == "__main__":
    main()
