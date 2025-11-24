from aiogram import Router, types
from services.message_service import save_message

router = Router()

@router.message()
async def message_handler(msg: types.Message):
    save_message(msg)
