from aiogram import Router
from aiogram.types import MessageReactionUpdated
from bot.services.message_service import save_reaction

router = Router()

@router.chat_member()   # или событийный хендлер для реакций
async def reaction_handler(event: MessageReactionUpdated):
    save_reaction(event)
