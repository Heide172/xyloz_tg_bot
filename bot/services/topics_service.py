import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta

import aiohttp
import numpy as np
from sklearn.cluster import KMeans
from sqlalchemy import func

from common.db.db import SessionLocal
from common.logger.logger import get_logger
from common.models.message import Message
from common.models.user import User
from services import ai_client
from services.summary_service import get_summary_model

logger = get_logger(__name__)

NLP_SERVICE_URL = os.getenv("NLP_SERVICE_URL", "http://nlp:8000").rstrip("/")
EMBED_TIMEOUT_SEC = float(os.getenv("NLP_EMBED_TIMEOUT_SEC", "120"))

TOPICS_DEFAULT_DAYS = 7
TOPICS_MIN_DAYS = 1
TOPICS_MAX_DAYS = 30
TOPICS_MIN_MESSAGES = 30
TOPICS_MAX_MESSAGES = 1500
TOPICS_MIN_MESSAGE_LEN = 20
NUM_CLUSTERS = 8
MIN_CLUSTER_SIZE = 4
EXAMPLES_PER_CLUSTER = 3
AUTHORS_PER_CLUSTER = 5


def parse_topics_days(text: str, default: int = TOPICS_DEFAULT_DAYS) -> int:
    parts = (text or "").split()
    if len(parts) < 2:
        return default
    try:
        v = int(parts[1])
    except ValueError:
        raise ValueError("Дни должны быть числом, пример: /topics 7")
    if v < TOPICS_MIN_DAYS or v > TOPICS_MAX_DAYS:
        raise ValueError(f"Дни должны быть в диапазоне {TOPICS_MIN_DAYS}..{TOPICS_MAX_DAYS}")
    return v


def _author_label(username: str | None, fullname: str | None) -> str:
    if username:
        return f"@{username}"
    if fullname:
        return fullname
    return "Unknown"


def _fetch_messages(chat_id: int, days: int) -> list[tuple[int, str, str]]:
    since = datetime.utcnow() - timedelta(days=days)
    session = SessionLocal()
    try:
        rows = (
            session.query(Message.id, User.username, User.fullname, Message.text)
            .outerjoin(User, Message.user_id == User.id)
            .filter(
                Message.chat_id == chat_id,
                Message.created_at >= since,
                Message.text.isnot(None),
                Message.text != "",
                func.length(Message.text) >= TOPICS_MIN_MESSAGE_LEN,
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        return [
            (row.id, _author_label(row.username, row.fullname), (row.text or "").strip())
            for row in rows
        ]
    finally:
        session.close()


async def _fetch_embeddings(texts: list[str]) -> np.ndarray | None:
    if not texts:
        return None
    timeout = aiohttp.ClientTimeout(total=EMBED_TIMEOUT_SEC)
    url = f"{NLP_SERVICE_URL}/embed/batch"
    async with aiohttp.ClientSession() as http:
        async with http.post(url, json={"texts": texts}, timeout=timeout) as resp:
            resp.raise_for_status()
            body = await resp.json()
    embeds = body.get("embeddings") or []
    if not embeds:
        return None
    return np.array(embeds, dtype=np.float32)


def _cluster_kmeans(embeddings: np.ndarray, k: int) -> np.ndarray:
    actual_k = max(2, min(k, len(embeddings)))
    km = KMeans(n_clusters=actual_k, n_init=4, random_state=42, max_iter=100)
    return km.fit_predict(embeddings)


def _label_clusters_with_llm(examples_per_cluster: dict[int, list[str]]) -> dict[int, str]:
    if not examples_per_cluster:
        return {}

    lines = [
        "Ниже несколько кластеров сообщений из чата. Для каждого назови тему 2-4 словами на русском.",
        "Тема должна быть конкретной (что обсуждали), а не общей («разговоры»/«разное» — запрещено).",
        "Сленг и мат сохраняй, не цензурируй.",
        "",
    ]
    for cid, examples in sorted(examples_per_cluster.items()):
        lines.append(f"CLUSTER {cid}:")
        for ex in examples[:5]:
            ex_clip = ex[:180].replace("\n", " ")
            lines.append(f"  - {ex_clip}")
        lines.append("")
    lines.append("Ответ строго в формате (одна тема — одна строка):")
    lines.append("CLUSTER 0: тема")
    lines.append("CLUSTER 1: тема")
    prompt = "\n".join(lines)

    try:
        raw = ai_client.call(
            prompt,
            get_summary_model(),
            "Ты выделяешь конкретные темы из сообщений русскоязычного чата. Тема — 2-4 слова. Никаких объяснений. Сленг и мат сохраняй.",
        )
    except Exception:
        logger.exception("topic labeling LLM call failed")
        return {}

    out: dict[int, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.upper().startswith("CLUSTER"):
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        try:
            cid = int(parts[0].replace("CLUSTER", "").replace("cluster", "").strip())
        except ValueError:
            continue
        label = parts[1].strip()
        if label:
            out[cid] = label
    return out


async def discover_topics(chat_id: int, days: int) -> list[dict] | None:
    rows = await asyncio.to_thread(_fetch_messages, chat_id, days)
    if len(rows) < TOPICS_MIN_MESSAGES:
        return None

    if len(rows) > TOPICS_MAX_MESSAGES:
        step = len(rows) / TOPICS_MAX_MESSAGES
        rows = [rows[min(int(i * step), len(rows) - 1)] for i in range(TOPICS_MAX_MESSAGES)]

    authors = [r[1] for r in rows]
    texts = [r[2] for r in rows]

    embeds = await _fetch_embeddings(texts)
    if embeds is None:
        return None

    labels = await asyncio.to_thread(_cluster_kmeans, embeds, NUM_CLUSTERS)

    clusters: dict[int, dict] = {}
    for i, cid in enumerate(labels):
        cid = int(cid)
        clusters.setdefault(cid, {"texts": [], "authors": [], "idx": []})
        clusters[cid]["texts"].append(texts[i])
        clusters[cid]["authors"].append(authors[i])
        clusters[cid]["idx"].append(i)

    clusters = {cid: c for cid, c in clusters.items() if len(c["texts"]) >= MIN_CLUSTER_SIZE}
    if not clusters:
        return []

    examples_for_label: dict[int, list[str]] = {}
    for cid, c in clusters.items():
        idx = c["idx"]
        cluster_embeds = embeds[idx]
        centroid = cluster_embeds.mean(axis=0)
        norms = np.linalg.norm(cluster_embeds, axis=1) * np.linalg.norm(centroid) + 1e-9
        sims = (cluster_embeds @ centroid) / norms
        nearest_local = np.argsort(-sims)[:5]
        nearest_texts = [c["texts"][int(j)] for j in nearest_local]
        examples_for_label[cid] = nearest_texts
        c["nearest"] = nearest_texts[:EXAMPLES_PER_CLUSTER]

    cluster_labels = await asyncio.to_thread(_label_clusters_with_llm, examples_for_label)

    result: list[dict] = []
    for cid, c in sorted(clusters.items(), key=lambda x: -len(x[1]["texts"])):
        author_counts = Counter(c["authors"])
        top_authors = [a for a, _ in author_counts.most_common(AUTHORS_PER_CLUSTER)]
        result.append({
            "label": cluster_labels.get(cid, f"Тема {cid}"),
            "size": len(c["texts"]),
            "examples": c["nearest"],
            "authors": top_authors,
        })
    return result
