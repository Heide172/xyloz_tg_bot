"""Диагностика покрытия эмбеддингами.

Показывает per-chat: всего eligible сообщений / уже эмбедженных / свежесть.
"""
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

QUERY = """
WITH eligible AS (
    SELECT m.id, m.chat_id, m.created_at
    FROM messages m
    WHERE m.text IS NOT NULL AND m.text != '' AND length(m.text) >= 10
),
emb AS (
    SELECT e.message_id, m.chat_id, m.created_at
    FROM message_embeddings e
    JOIN messages m ON m.id = e.message_id
)
SELECT
    e1.chat_id,
    COUNT(*) AS total_eligible,
    COUNT(e2.message_id) AS embedded,
    MAX(e1.created_at) AS latest_msg,
    MAX(e2.created_at) AS latest_embedded
FROM eligible e1
LEFT JOIN emb e2 ON e2.message_id = e1.id
GROUP BY e1.chat_id
ORDER BY total_eligible DESC;
"""


def main() -> None:
    with engine.begin() as c:
        rows = c.exec_driver_sql(QUERY).fetchall()
        if not rows:
            print("нет сообщений")
            return
        print(f"{'chat_id':>20} | {'eligible':>10} | {'embedded':>10} | {'coverage':>8} | latest_msg          | latest_embedded     | gap")
        print("-" * 130)
        for row in rows:
            chat_id, total, emb, latest_msg, latest_emb = row
            coverage = (emb / total * 100) if total else 0
            gap = "—"
            if latest_msg and latest_emb:
                delta_sec = (latest_msg - latest_emb).total_seconds()
                if delta_sec < 60:
                    gap = f"{int(delta_sec)}s"
                elif delta_sec < 3600:
                    gap = f"{int(delta_sec/60)}m"
                elif delta_sec < 86400:
                    gap = f"{delta_sec/3600:.1f}h"
                else:
                    gap = f"{delta_sec/86400:.1f}d"
            lm = latest_msg.strftime("%Y-%m-%d %H:%M") if latest_msg else "—"
            le = latest_emb.strftime("%Y-%m-%d %H:%M") if latest_emb else "—"
            print(f"{chat_id:>20} | {total:>10} | {emb:>10} | {coverage:>6.1f}% | {lm:>19} | {le:>19} | {gap}")
        print("-" * 130)
        total_all = sum(r[1] for r in rows)
        emb_all = sum(r[2] for r in rows)
        print(f"{'TOTAL':>20} | {total_all:>10} | {emb_all:>10} | {emb_all/total_all*100:>6.1f}%")


if __name__ == "__main__":
    main()
