from aiogram import Router
from aiogram.types import MessageReactionUpdated

from services.message_service import save_reaction

router = Router()


@router.message_reaction()
async def reaction_handler(event: MessageReactionUpdated):
    save_reaction(event)
