"""Фильтрация шума и группировка сообщений по чату -> топику."""
from collections import defaultdict
from dataclasses import dataclass, field

from common.models import VpnMessage

_NOISE = {
    "+", "++", "+++", "спс", "спасибо", "пасиб", "благодарю", "да", "нет", "ок", "ок.",
    "ага", "угу", "ясно", "понятно", "👍", "👌", "🔥", ".", "..", "...", "лол", "ха",
    "хаха", "тоже", "и я", "у меня тоже", "+1",
}

MIN_TOPIC_MESSAGES = 3  # топики с меньшим числом осмысленных сообщений пропускаем


def _is_noise(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or t in _NOISE or len(t) <= 2:
        return True
    return False


@dataclass
class TopicBucket:
    chat_id: int
    chat_title: str
    topic_id: int | None
    topic_title: str
    messages: list[VpnMessage] = field(default_factory=list)

    def render(self) -> str:
        lines = []
        for m in self.messages:
            who = m.username or (str(m.user_id) if m.user_id else "?")
            reply = f" (↪ #{m.reply_to})" if m.reply_to else ""
            lines.append(f"[#{m.telegram_message_id}{reply}] {who}: {m.text}")
        return "\n".join(lines)


def group_into_topics(
    messages: list[VpnMessage],
    chat_titles: dict[int, str] | None = None,
) -> list[TopicBucket]:
    chat_titles = chat_titles or {}
    buckets: dict[tuple[int, int | None], TopicBucket] = {}

    for m in messages:
        if _is_noise(m.text):
            continue
        key = (m.chat_id, m.topic_id)
        b = buckets.get(key)
        if b is None:
            b = TopicBucket(
                chat_id=m.chat_id,
                chat_title=chat_titles.get(m.chat_id, str(m.chat_id)),
                topic_id=m.topic_id,
                topic_title=(m.topic_title or "General"),
            )
            buckets[key] = b
        b.messages.append(m)

    result = [b for b in buckets.values() if len(b.messages) >= MIN_TOPIC_MESSAGES]
    result.sort(key=lambda b: len(b.messages), reverse=True)
    return result


def chats_summary(buckets: list[TopicBucket]) -> dict[int, list[TopicBucket]]:
    by_chat: dict[int, list[TopicBucket]] = defaultdict(list)
    for b in buckets:
        by_chat[b.chat_id].append(b)
    return by_chat
