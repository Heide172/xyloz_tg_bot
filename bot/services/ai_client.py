"""Единый AI-клиент поверх OpenAI SDK.

Бэкенд: OpenCode Go (https://opencode.ai/go), OpenAI-compatible.
Все вызовы идут через стрим, чтобы избежать Cloudflare 524 при медленных моделях.

Если модель отдаёт reasoning_content (qwen3.6, gpt-oss и другие reasoning-семейства) —
он попадает в опциональный callback `on_reasoning`.
"""
import logging
import os
from typing import Callable

from openai import OpenAI

logger = logging.getLogger(__name__)


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and v != "":
            return v
    return default


OPENCODE_BASE_URL = _env("OPENCODE_BASE_URL", default="https://opencode.ai/zen/go/v1").rstrip("/")
MAX_OUTPUT_TOKENS = int(_env("AI_MAX_OUTPUT_TOKENS", default="16000"))
AI_CALL_TIMEOUT_SEC = float(_env("AI_CALL_TIMEOUT_SEC", default="300"))
AI_STREAM_TIMEOUT_SEC = float(_env("AI_STREAM_TIMEOUT_SEC", default="300"))

OPENCODE_PREFIX = "opencode-go/"

_client: OpenAI | None = None


def _get_api_key() -> str:
    value = (os.getenv("OPENCODE_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("OPENCODE_API_KEY не задан")
    return value


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=_get_api_key(),
            base_url=OPENCODE_BASE_URL,
            timeout=AI_STREAM_TIMEOUT_SEC,
            default_headers={
                "User-Agent": "xyloz-tg-bot/1.0 (+https://github.com/Heide172/xyloz_tg_bot)",
                "HTTP-Referer": "https://github.com/Heide172/xyloz_tg_bot",
                "X-Title": "xyloz_tg_bot",
            },
        )
    return _client


def _strip_prefix(model: str) -> str:
    return model.removeprefix(OPENCODE_PREFIX)


def _build_messages(user_prompt: str, system_prompt: str | None) -> list[dict]:
    msgs: list[dict] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs


def stream(
    user_prompt: str,
    model: str,
    on_delta: Callable[[str], None],
    system_prompt: str | None = None,
    on_reasoning: Callable[[str], None] | None = None,
) -> str:
    """Стримит ответ модели. Возвращает финальный content.

    on_delta вызывается на каждую дельту обычного ответа (content).
    on_reasoning — на дельту reasoning_content, если модель его отдаёт.
    """
    client = get_client()
    model_id = _strip_prefix(model)
    messages = _build_messages(user_prompt, system_prompt)

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None

    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=0.0,
            max_tokens=MAX_OUTPUT_TOKENS,
            stream=True,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            content_piece = getattr(delta, "content", None)
            if content_piece:
                content_parts.append(content_piece)
                on_delta(content_piece)

            # Разные провайдеры используют разные поля под reasoning.
            reasoning_piece = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_piece:
                reasoning_parts.append(reasoning_piece)
                if on_reasoning is not None:
                    on_reasoning(reasoning_piece)
    except Exception as exc:
        logger.exception("opencode stream failed: model=%s", model_id)
        text = "".join(content_parts).strip()
        if text:
            return text
        raise RuntimeError(f"OpenCode stream error ({model_id}): {exc}") from exc

    text = "".join(content_parts).strip()
    if text:
        return text

    reasoning_len = len("".join(reasoning_parts))
    hint = ""
    if finish_reason:
        hint += f" (finish_reason={finish_reason})"
    if reasoning_len:
        hint += f" (reasoning_chars={reasoning_len} — модель ушла в reasoning, подними AI_MAX_OUTPUT_TOKENS или смени модель)"
    raise RuntimeError(f"OpenCode не вернул content для {model_id}{hint}")


def call(user_prompt: str, model: str, system_prompt: str | None = None) -> str:
    """Не-стриминговый интерфейс. Под капотом — тот же стрим с пустым callback."""
    return stream(user_prompt, model, lambda _d: None, system_prompt)
