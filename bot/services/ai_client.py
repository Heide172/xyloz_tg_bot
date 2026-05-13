import json
import logging
import os
import time
from typing import Callable
from urllib import error, request

logger = logging.getLogger(__name__)


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and v != "":
            return v
    return default


YANDEX_CHAT_COMPLETIONS_URL = _env(
    "YANDEX_CHAT_COMPLETIONS_URL",
    default="https://llm.api.cloud.yandex.net/v1/chat/completions",
)
OPENCODE_BASE_URL = _env(
    "OPENCODE_BASE_URL",
    default="https://opencode.ai/zen/go/v1",
).rstrip("/")
MAX_OUTPUT_TOKENS = int(_env("AI_MAX_OUTPUT_TOKENS", "YANDEX_MAX_OUTPUT_TOKENS", "OPENROUTER_MAX_OUTPUT_TOKENS", default="16000"))
AI_MAX_RETRIES = max(1, int(_env("AI_MAX_RETRIES", "YANDEX_MAX_RETRIES", default="2")))
AI_RETRY_DELAY_SEC = float(_env("AI_RETRY_DELAY_SEC", "YANDEX_RETRY_DELAY_SEC", default="1.5"))

OPENCODE_PREFIX = "opencode-go/"


def get_yandex_api_key() -> str:
    value = (os.getenv("YANDEX_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("YANDEX_API_KEY не задан")
    return value


def get_yandex_folder_id() -> str:
    value = (os.getenv("YANDEX_FOLDER_ID") or "").strip()
    if not value:
        raise RuntimeError("YANDEX_FOLDER_ID не задан")
    return value


def resolve_model_uri(model_value: str, folder_id: str) -> str:
    m = model_value.strip()
    if m.startswith("gpt://"):
        return m
    return f"gpt://{folder_id}/{m}"


def _extract_text_payload(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_message_content(body: dict) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message", {}) if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    return _extract_text_payload(message.get("content"))


def _build_messages(user_prompt: str, system_prompt: str | None) -> list[dict]:
    # Single user-role message: Yandex и многие free-providers некорректно работают с system role.
    content = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
    return [{"role": "user", "content": content}]


def _build_messages_system(user_prompt: str, system_prompt: str | None) -> list[dict]:
    # Стандартный OpenAI-формат: отдельная system role.
    msgs: list[dict] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs


def get_opencode_api_key() -> str:
    value = (os.getenv("OPENCODE_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("OPENCODE_API_KEY не задан")
    return value


def is_opencode_model(model: str) -> bool:
    return model.startswith(OPENCODE_PREFIX)


def _opencode_model_id(model: str) -> str:
    return model.removeprefix(OPENCODE_PREFIX)


def call_yandex(user_prompt: str, model: str, system_prompt: str | None = None) -> str:
    api_key = get_yandex_api_key()
    folder_id = get_yandex_folder_id()
    model_uri = resolve_model_uri(model, folder_id)

    payload = {
        "model": model_uri,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": _build_messages(user_prompt, system_prompt),
    }

    last_error = ""
    for attempt in range(AI_MAX_RETRIES):
        req = request.Request(
            YANDEX_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "OpenAI-Project": folder_id,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw)
            text = _extract_message_content(body).strip()
            if text:
                return text
            # Пустой content — логируем тело, чтобы понять что вернул сервер.
            logger.error(
                "Yandex returned empty content. model=%s payload_chars=%d raw_response=%s",
                model_uri,
                len(json.dumps(payload)),
                raw[:2000],
            )
            # Попробуем извлечь подсказку из тела
            finish_reason = ""
            err_msg = ""
            reasoning_len = 0
            if isinstance(body, dict):
                choices = body.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    finish_reason = str(choices[0].get("finish_reason") or "")
                    msg = choices[0].get("message") or {}
                    if isinstance(msg, dict):
                        rc = msg.get("reasoning_content") or ""
                        if isinstance(rc, str):
                            reasoning_len = len(rc)
                err_msg = str(body.get("error") or body.get("message") or "")
            hint = ""
            if finish_reason:
                hint += f" (finish_reason={finish_reason})"
            if reasoning_len:
                hint += f" (reasoning_chars={reasoning_len} — модель ушла в reasoning и не дошла до content; подними AI_MAX_OUTPUT_TOKENS)"
            if err_msg:
                hint += f" (api_msg={err_msg[:200]})"
            raise RuntimeError(f"Yandex API вернул пустой ответ{hint}")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_uri}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < AI_MAX_RETRIES:
                time.sleep(AI_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"Yandex API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"Yandex API недоступен: {exc.reason}")

    raise RuntimeError(f"Yandex API error: {last_error or 'unknown'}")


def call_opencode(user_prompt: str, model: str, system_prompt: str | None = None) -> str:
    api_key = get_opencode_api_key()
    model_id = _opencode_model_id(model)
    url = f"{OPENCODE_BASE_URL}/chat/completions"

    payload = {
        "model": model_id,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": _build_messages_system(user_prompt, system_prompt),
    }

    last_error = ""
    for attempt in range(AI_MAX_RETRIES):
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Heide172/xyloz_tg_bot",
                "X-Title": "xyloz_tg_bot",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw)
            text = _extract_message_content(body).strip()
            if text:
                return text
            logger.error("OpenCode empty content. model=%s raw=%s", model_id, raw[:2000])
            raise RuntimeError(f"OpenCode API вернул пустой ответ для {model_id}")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_id}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < AI_MAX_RETRIES:
                time.sleep(AI_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"OpenCode API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"OpenCode API недоступен: {exc.reason}")

    raise RuntimeError(f"OpenCode API error: {last_error or 'unknown'}")


def stream_opencode(
    user_prompt: str,
    model: str,
    on_delta: Callable[[str], None],
    system_prompt: str | None = None,
) -> str:
    api_key = get_opencode_api_key()
    model_id = _opencode_model_id(model)
    url = f"{OPENCODE_BASE_URL}/chat/completions"

    payload = {
        "model": model_id,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": True,
        "messages": _build_messages_system(user_prompt, system_prompt),
    }

    last_error = ""
    for attempt in range(AI_MAX_RETRIES):
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Heide172/xyloz_tg_bot",
                "X-Title": "xyloz_tg_bot",
            },
            method="POST",
        )

        full_text: list[str] = []
        saw_done = False
        hard_error = False
        try:
            with request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[5:].strip()
                    if payload_line == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        last_error = f"{model_id}: {chunk.get('error')}"
                        hard_error = True
                        break
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first_choice = choices[0] if isinstance(choices[0], dict) else {}
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason:
                        saw_done = True
                    delta = first_choice.get("delta", {}) if isinstance(first_choice.get("delta", {}), dict) else {}
                    content_delta = _extract_text_payload(delta.get("content"))
                    if content_delta:
                        full_text.append(content_delta)
                        on_delta(content_delta)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_id}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < AI_MAX_RETRIES:
                time.sleep(AI_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"OpenCode API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"OpenCode API недоступен: {exc.reason}")

        text = "".join(full_text).strip()
        if text and not hard_error:
            if saw_done:
                return text
            try:
                completed = call_opencode(user_prompt, model, system_prompt).strip()
                if completed:
                    return completed
            except Exception:
                pass
            return text
        if hard_error:
            break

    raise RuntimeError(f"OpenCode API error: {last_error or 'unknown'}")


# ---------------- provider dispatch ----------------


def call(user_prompt: str, model: str, system_prompt: str | None = None) -> str:
    if is_opencode_model(model):
        return call_opencode(user_prompt, model, system_prompt)
    return call_yandex(user_prompt, model, system_prompt)


def stream(
    user_prompt: str,
    model: str,
    on_delta: Callable[[str], None],
    system_prompt: str | None = None,
) -> str:
    if is_opencode_model(model):
        return stream_opencode(user_prompt, model, on_delta, system_prompt)
    return stream_yandex(user_prompt, model, on_delta, system_prompt)


def stream_yandex(
    user_prompt: str,
    model: str,
    on_delta: Callable[[str], None],
    system_prompt: str | None = None,
) -> str:
    api_key = get_yandex_api_key()
    folder_id = get_yandex_folder_id()
    model_uri = resolve_model_uri(model, folder_id)

    payload = {
        "model": model_uri,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "stream": True,
        "messages": _build_messages(user_prompt, system_prompt),
    }

    last_error = ""
    for attempt in range(AI_MAX_RETRIES):
        req = request.Request(
            YANDEX_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "OpenAI-Project": folder_id,
            },
            method="POST",
        )

        full_text: list[str] = []
        saw_done = False
        hard_error = False
        try:
            with request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_line = line[5:].strip()
                    if payload_line == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(payload_line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        last_error = f"{model_uri}: {chunk.get('error')}"
                        hard_error = True
                        break
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first_choice = choices[0] if isinstance(choices[0], dict) else {}
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason:
                        saw_done = True
                    delta = first_choice.get("delta", {}) if isinstance(first_choice.get("delta", {}), dict) else {}
                    content_delta = _extract_text_payload(delta.get("content"))
                    if content_delta:
                        full_text.append(content_delta)
                        on_delta(content_delta)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"{model_uri}: {exc.code} {details[:200]}"
            if exc.code == 429 and attempt + 1 < AI_MAX_RETRIES:
                time.sleep(AI_RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise RuntimeError(f"Yandex API error: {last_error}")
        except error.URLError as exc:
            raise RuntimeError(f"Yandex API недоступен: {exc.reason}")

        text = "".join(full_text).strip()
        if text and not hard_error:
            if saw_done:
                return text
            # Стрим прервался без [DONE] — пробуем добить non-stream запросом.
            try:
                completed = call_yandex(user_prompt, model, system_prompt).strip()
                if completed:
                    return completed
            except Exception:
                pass
            return text
        last_error = last_error or (
            f"{model_uri}: stream ended without final content (possibly reasoning-only response)"
        )
        if hard_error:
            break

    raise RuntimeError(f"Yandex API error: {last_error or 'unknown'}")
