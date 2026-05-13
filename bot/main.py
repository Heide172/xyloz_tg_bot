import asyncio
import os
from aiogram import Bot, Dispatcher
from handlers.digest import router as digest_router
from handlers.messages import router as message_router
from handlers.reactions import router as reaction_router
from handlers.statistic import router as stats_router
from services.scheduler import start_scheduler
from common.logger.logger import get_logger
logger = get_logger(__name__)

async def main():
    bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
    dp = Dispatcher()
    dp.include_router(stats_router)
    dp.include_router(message_router)
    dp.include_router(reaction_router)
    dp.include_router(digest_router)

    scheduler = start_scheduler(bot)
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)

if __name__ == "__main__":
    asyncio.run(main())
