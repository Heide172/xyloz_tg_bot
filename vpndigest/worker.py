"""Генерация дайджеста: map-reduce -> markdown -> сохранение -> доставка.

    python -m vpndigest.worker --once      # один прогон сейчас
    python -m vpndigest.worker             # демон по расписанию VPN_DIGEST_CRON
"""
import argparse
from datetime import datetime, timedelta

from common.logger import get_logger
from common.models import VpnDigest
from vpndigest import config, grouping, summarize
from vpndigest.publish import deliver
from vpndigest.storage import session_scope, fetch_window, chat_titles

log = get_logger("vpndigest.worker")


def _build_markdown(tldr: str, by_chat, topic_summaries, period: str) -> str:
    out = [f"📰 *Дайджест VPN-чатов* — {period}", "", "*TL;DR*", tldr.strip(), ""]
    for chat_id, buckets in by_chat.items():
        out.append(f"\n━━━ *{buckets[0].chat_title}* ━━━")
        for b in buckets:
            summary = topic_summaries.get((b.chat_id, b.topic_id), "").strip()
            if not summary:
                continue
            if b.topic_id is not None:
                out.append(f"\n*🧵 {b.topic_title}* ({len(b.messages)} сообщ.)")
            else:
                out.append(f"\n({len(b.messages)} сообщ.)")
            out.append(summary)
    return "\n".join(out)


def run_once(window_hours: int | None = None) -> VpnDigest | None:
    end = datetime.utcnow()
    hours = window_hours or config.VPN_DIGEST_WINDOW_HOURS
    start = end - timedelta(hours=hours)
    period = f"{start:%d.%m %H:%M}–{end:%d.%m %H:%M} UTC"
    log.info("Собираю дайджест за %s", period)

    messages = fetch_window(start, end)
    buckets = grouping.group_into_topics(messages, chat_titles())
    if not buckets:
        log.info("Нет осмысленных обсуждений за период — дайджест не формирую.")
        return None

    log.info("Топиков: %d (сообщений: %d)", len(buckets), len(messages))

    # MAP: саммари на топик
    topic_summaries: dict[tuple[int, int | None], str] = {}
    for b in buckets:
        try:
            topic_summaries[(b.chat_id, b.topic_id)] = summarize.summarize_topic(b, period)
        except Exception:
            log.exception("Не смог суммировать топик %s/%s", b.chat_id, b.topic_id)

    if not topic_summaries:
        log.warning("Все топик-саммари упали — пропускаю дайджест.")
        return None

    # REDUCE: общий TL;DR
    joined = "\n\n".join(
        f"### {b.chat_title} / {b.topic_title}\n{topic_summaries[(b.chat_id, b.topic_id)]}"
        for b in buckets
        if (b.chat_id, b.topic_id) in topic_summaries
    )
    try:
        tldr = summarize.make_tldr(joined, period)
    except Exception:
        log.exception("Reduce-шаг (TL;DR) упал — заглушка.")
        tldr = "_(не удалось сгенерировать общий TL;DR)_"

    by_chat = grouping.chats_summary(buckets)
    content = _build_markdown(tldr, by_chat, topic_summaries, period)

    with session_scope() as s:
        d = VpnDigest(
            period_start=start,
            period_end=end,
            chat_id=None,
            content=content,
            model=config.VPN_DIGEST_MODEL,
            messages_count=len(messages),
            delivered=False,
        )
        s.add(d)
        s.flush()
        digest_id = d.id

    try:
        deliver(content)
        with session_scope() as s:
            s.get(VpnDigest, digest_id).delivered = True
        log.info("Дайджест #%s сформирован и доставлен.", digest_id)
    except Exception:
        log.exception("Дайджест #%s сохранён, но доставка не удалась.", digest_id)

    with session_scope() as s:
        return s.get(VpnDigest, digest_id)


def run_scheduler():
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BlockingScheduler(timezone=config.VPN_TZ)
    trigger = CronTrigger.from_crontab(config.VPN_DIGEST_CRON, timezone=config.VPN_TZ)
    sched.add_job(run_once, trigger, id="vpn_digest", misfire_grace_time=3600)
    log.info("Планировщик запущен: cron='%s' tz=%s", config.VPN_DIGEST_CRON, config.VPN_TZ)
    sched.start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="один прогон сейчас и выход")
    ap.add_argument("--hours", type=int, default=None, help="окно в часах (override)")
    args = ap.parse_args()
    if args.once:
        run_once(args.hours)
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
