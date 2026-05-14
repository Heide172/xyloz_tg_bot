import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeDefault
from handlers.admin_status import router as admin_status_router
from handlers.ask import router as ask_router
from handlers.casino import router as casino_router
from handlers.digest import router as digest_router
from handlers.economy import router as economy_router
from handlers.joke import router as joke_router
from handlers.markets import router as markets_router
from handlers.messages import router as message_router
from handlers.rules import router as rules_router
from handlers.mood import router as mood_router
from handlers.reactions import router as reaction_router
from handlers.statistic import router as stats_router
from handlers.topics import router as topics_router
from handlers.user_card import router as user_card_router
from services.scheduler import start_scheduler
from common.logger.logger import get_logger
logger = get_logger(__name__)


PUBLIC_COMMANDS = [
    BotCommand(command="help", description="Все команды"),
    BotCommand(command="summary", description="Пересказ последних сообщений"),
    BotCommand(command="digest", description="Дайджест чата за период"),
    BotCommand(command="card", description="Карточка участника"),
    BotCommand(command="mood", description="Настроение чата"),
    BotCommand(command="toxic", description="Топ токсичных авторов"),
    BotCommand(command="topics", description="Темы чата за период"),
    BotCommand(command="ask", description="Поиск ответа в истории чата"),
    BotCommand(command="mystats", description="Твоя статистика"),
    BotCommand(command="chatstats", description="Статистика чата"),
    BotCommand(command="who", description="Список активных участников"),
    BotCommand(command="peakday", description="Топ-3 активных дня"),
    BotCommand(command="streak", description="Стрики активности"),
    BotCommand(command="fag", description="Случайный участник дня"),
    BotCommand(command="joke", description="Анекдот дня"),
    BotCommand(command="phrase", description="Фраза дня в стиле чата"),
    BotCommand(command="balance", description="Твой баланс гривен"),
    BotCommand(command="leaderboard", description="Топ балансов чата"),
    BotCommand(command="economy", description="Экономика чата"),
    BotCommand(command="transfer", description="Перевод гривен другому"),
    BotCommand(command="market_create", description="Создать рынок ставок"),
    BotCommand(command="markets", description="Список рынков"),
    BotCommand(command="market", description="Карточка рынка"),
    BotCommand(command="bet", description="Поставить на рынок"),
    BotCommand(command="portfolio", description="Мои ставки"),
    BotCommand(command="market_import", description="Импорт рынка из polymarket/manifold"),
    BotCommand(command="casino", description="Открыть Mini App: ставки и баланс"),
    BotCommand(command="rules", description="Правила Бурмалды: экономика и ставки"),
]

ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="model_show", description="Текущая AI-модель"),
    BotCommand(command="model_list", description="Доступные модели"),
    BotCommand(command="model_set", description="Сменить AI-модель"),
    BotCommand(command="prompt_show", description="Текущий промпт"),
    BotCommand(command="prompt_set", description="Сменить промпт"),
    BotCommand(command="prompt_reset", description="Сбросить промпт"),
    BotCommand(command="admin_status", description="Полное состояние бота"),
    BotCommand(command="backfill", description="Управление backfill jobs"),
    BotCommand(command="admin_adjust", description="Корректировка баланса"),
    BotCommand(command="market_resolve", description="Закрыть рынок и выплатить"),
    BotCommand(command="market_cancel", description="Отменить рынок с возвратом"),
]


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeAllChatAdministrators())
    logger.info("bot commands registered: %d public, %d admin", len(PUBLIC_COMMANDS), len(ADMIN_COMMANDS))


async def main():
    bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
    dp = Dispatcher()
    dp.include_router(stats_router)
    dp.include_router(digest_router)
    dp.include_router(user_card_router)
    dp.include_router(mood_router)
    dp.include_router(topics_router)
    dp.include_router(ask_router)
    dp.include_router(joke_router)
    dp.include_router(economy_router)
    dp.include_router(markets_router)
    dp.include_router(casino_router)
    dp.include_router(rules_router)
    dp.include_router(admin_status_router)
    dp.include_router(message_router)
    dp.include_router(reaction_router)

    await setup_commands(bot)
    scheduler = start_scheduler(bot)
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)

if __name__ == "__main__":
    asyncio.run(main())
