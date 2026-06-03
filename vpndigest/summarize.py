"""LLM-саммаризация через общий ai_client xyloz (бэкенд OpenCode)."""
from bot.services import ai_client

from vpndigest import config, prompts
from vpndigest.grouping import TopicBucket

# Ограничение на объём диалога одного топика, подаваемого в LLM (символы)
_MAX_TOPIC_CHARS = 12000


def summarize_topic(bucket: TopicBucket, period: str) -> str:
    dialog = bucket.render()
    if len(dialog) > _MAX_TOPIC_CHARS:
        dialog = dialog[-_MAX_TOPIC_CHARS:]  # хвост = свежее
    user = prompts.TOPIC_USER_TEMPLATE.format(
        chat=bucket.chat_title, topic=bucket.topic_title, period=period, messages=dialog
    )
    return ai_client.call(user, config.VPN_DIGEST_MODEL, prompts.TOPIC_SYSTEM)


def make_tldr(joined_summaries: str, period: str) -> str:
    user = prompts.TLDR_USER_TEMPLATE.format(period=period, summaries=joined_summaries)
    return ai_client.call(user, config.VPN_DIGEST_MODEL, prompts.TLDR_SYSTEM)
