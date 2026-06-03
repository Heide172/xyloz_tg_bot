"""Одноразовый интерактивный логin -> печатает VPN_SESSION_STRING для .env.

Запусти ЛОКАЛЬНО (не в контейнере) с ОТДЕЛЬНОГО аккаунта:
    python -m vpndigest.login
"""
import asyncio

from pyrogram import Client

from vpndigest import config


async def main():
    if not config.TG_API_ID or not config.TG_API_HASH:
        raise SystemExit("Заполни TG_API_ID и TG_API_HASH в .env (my.telegram.org)")

    async with Client("vpn_login_tmp", api_id=config.TG_API_ID,
                      api_hash=config.TG_API_HASH, in_memory=True) as app:
        me = await app.get_me()
        session = await app.export_session_string()
        print("\n" + "=" * 70)
        print(f"✅ Залогинен как @{me.username} (id={me.id})")
        print("Вставь строку в .env как VPN_SESSION_STRING (никому не показывай!):\n")
        print(session)
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
