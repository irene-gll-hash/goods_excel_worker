import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import os
from bot.handlers import router
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

logging.basicConfig(level=logging.INFO)
async def main():
    bot = Bot(
        token=os.getenv("BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("Бот запущен...")
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())
