"""VPN-digest: userbot-мониторинг чатов VPN-проекта + периодические дайджесты.

Встроено в инфраструктуру xyloz_tg_bot: общий Base/SessionLocal (common.db),
логгер (common.logger), LLM через bot.services.ai_client. Запускается двумя
сервисами docker-compose: vpn_userbot (listener) и vpn_digest_worker (расписание).
"""
