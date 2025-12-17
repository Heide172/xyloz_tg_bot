import asyncio
import os
from aiogram import Bot, Dispatcher
from handlers.messages import router as message_router
from handlers.reactions import router as reaction_router
from handlers.statistic import router as stats_router
from common.logger.logger import get_logger
logger = get_logger(__name__)

async def main():
    bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
    dp = Dispatcher()
    dp.include_router(stats_router)
    dp.include_router(message_router)
    dp.include_router(reaction_router)


    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
