import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import torch
from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline,
)


SENTIMENT_MODEL = os.getenv("NLP_SENTIMENT_MODEL", "seara/rubert-tiny2-russian-sentiment")
TOXICITY_MODEL = os.getenv("NLP_TOXICITY_MODEL", "cointegrated/rubert-tiny-toxicity")
MAX_LENGTH = int(os.getenv("NLP_MAX_LENGTH", "256"))
BATCH_SIZE = int(os.getenv("NLP_BATCH_SIZE", "32"))

logger = logging.getLogger("nlp")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_state: dict = {}


def _load_models():
    logger.info("loading sentiment model: %s", SENTIMENT_MODEL)
    tok_s = AutoTokenizer.from_pretrained(SENTIMENT_MODEL)
    mdl_s = AutoModelForSequenceClassification.from_pretrained(SENTIMENT_MODEL)
    _state["sentiment"] = pipeline(
        "text-classification",
        model=mdl_s,
        tokenizer=tok_s,
        device=-1,
        truncation=True,
        max_length=MAX_LENGTH,
        top_k=None,
    )

    logger.info("loading toxicity model: %s", TOXICITY_MODEL)
    tok_t = AutoTokenizer.from_pretrained(TOXICITY_MODEL)
    mdl_t = AutoModelForSequenceClassification.from_pretrained(TOXICITY_MODEL)
    _state["toxicity"] = pipeline(
        "text-classification",
        model=mdl_t,
        tokenizer=tok_t,
        device=-1,
        truncation=True,
        max_length=MAX_LENGTH,
        top_k=None,
    )
    logger.info("models ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_models()
    yield


app = FastAPI(lifespan=lifespan, title="xyloz-nlp", version="0.1.0")


class BatchRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class ClassifyResult(BaseModel):
    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None
    toxicity_score: Optional[float] = None


class BatchResponse(BaseModel):
    results: list[ClassifyResult]


def _normalize_sentiment_label(raw_label: str) -> str:
    low = raw_label.lower()
    if "pos" in low:
        return "positive"
    if "neg" in low:
        return "negative"
    if "neu" in low:
        return "neutral"
    return low


def _sentiment_score_signed(label: str, confidence: float) -> float:
    if label == "positive":
        return float(confidence)
    if label == "negative":
        return -float(confidence)
    return 0.0


def _extract_best(rows: list[dict]) -> tuple[str, float]:
    best = max(rows, key=lambda r: r["score"])
    return best["label"], float(best["score"])


def _extract_toxicity_prob(rows: list[dict]) -> float:
    for r in rows:
        lbl = r["label"].lower()
        if "toxic" in lbl and "non" not in lbl and "not" not in lbl:
            return float(r["score"])
    # fallback: predict highest score's complement if labels weird
    return 0.0


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "models_loaded": bool(_state)}


@app.post("/classify/batch", response_model=BatchResponse)
def classify_batch(req: BatchRequest) -> BatchResponse:
    texts = [t.strip() for t in req.texts]
    if not texts:
        return BatchResponse(results=[])

    sentiment_pipe = _state["sentiment"]
    toxicity_pipe = _state["toxicity"]

    with torch.no_grad():
        s_out = sentiment_pipe(texts, batch_size=BATCH_SIZE)
        t_out = toxicity_pipe(texts, batch_size=BATCH_SIZE)

    results: list[ClassifyResult] = []
    for s_rows, t_rows, text in zip(s_out, t_out, texts):
        if not text:
            results.append(ClassifyResult())
            continue
        s_label_raw, s_conf = _extract_best(s_rows)
        s_label = _normalize_sentiment_label(s_label_raw)
        results.append(
            ClassifyResult(
                sentiment_label=s_label,
                sentiment_score=_sentiment_score_signed(s_label, s_conf),
                toxicity_score=_extract_toxicity_prob(t_rows),
            )
        )
    return BatchResponse(results=results)
