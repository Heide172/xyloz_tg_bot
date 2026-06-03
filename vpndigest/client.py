"""Pyrogram Client от имени отдельного юзер-аккаунта (read-only мониторинг VPN-чатов)."""
from pyrogram import Client

from vpndigest import config


def build_client(name: str = "vpn_digest_userbot") -> Client:
    if not config.TG_API_ID or not config.TG_API_HASH:
        raise RuntimeError("TG_API_ID / TG_API_HASH не заданы в .env")
    if not config.VPN_SESSION_STRING:
        raise RuntimeError(
            "VPN_SESSION_STRING пуст. Запусти `python -m vpndigest.login` и вставь "
            "строку в .env как VPN_SESSION_STRING."
        )
    return Client(
        name=name,
        api_id=config.TG_API_ID,
        api_hash=config.TG_API_HASH,
        session_string=config.VPN_SESSION_STRING,
        in_memory=True,
        no_updates=False,
    )
