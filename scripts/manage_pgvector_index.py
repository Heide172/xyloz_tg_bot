"""Управление ivfflat-индексом на message_embeddings.

Перед bulk-load полезно DROP'нуть индекс, чтобы INSERT'ы не нагружали CPU
постгреса пересчётом кластеров. После backfill — пересоздать с правильным lists.

    python scripts/manage_pgvector_index.py status
    python scripts/manage_pgvector_index.py drop
    python scripts/manage_pgvector_index.py create [--lists 500]
"""
import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from common.db.db import engine

INDEX_NAME = "idx_message_embeddings_vec"
TABLE = "message_embeddings"


def cmd_status() -> None:
    with engine.begin() as c:
        count = c.exec_driver_sql(f"SELECT count(*) FROM {TABLE}").scalar()
        idx = c.exec_driver_sql(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            (INDEX_NAME,),
        ).first()
        print(f"rows in {TABLE}: {count}")
        if idx:
            print(f"index present:\n  {idx[0]}")
        else:
            print(f"index '{INDEX_NAME}' NOT present")


def cmd_drop() -> None:
    with engine.begin() as c:
        c.exec_driver_sql(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    print(f"dropped {INDEX_NAME}")


def cmd_create(lists: int | None) -> None:
    with engine.begin() as c:
        if lists is None:
            count = c.exec_driver_sql(f"SELECT count(*) FROM {TABLE}").scalar() or 0
            lists = max(10, int(math.sqrt(count)))
            print(f"auto lists = sqrt({count}) = {lists}")
        c.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
        )
    print(f"created {INDEX_NAME} with lists={lists}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("drop")
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--lists", type=int, default=None)
    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "drop":
        cmd_drop()
    elif args.cmd == "create":
        cmd_create(args.lists)


if __name__ == "__main__":
    main()
