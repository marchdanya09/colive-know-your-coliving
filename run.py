import asyncio
import logging
import sys
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import settings
from database.db import init_db
from bot.middlewares.anti_spam import AntiFloodMiddleware
from bot.handlers import start, user_menu, sotnik_panel, group_chat
from bot.scheduler import setup_scheduler
from webapp.api import app as webapp_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("CO:LIVE")

async def start_webapp():
    try:
        config = uvicorn.Config(
            app=webapp_app,
            host=settings.WEBAPP_HOST,
            port=settings.WEBAPP_PORT,
            log_level="warning"
        )
        server = uvicorn.Server(config)
        await server.serve()
    except Exception as e:
        logger.warning(f"Web App сервер не зміг підключитися до порту {settings.WEBAPP_PORT}: {e}")

async def main():
    logger.info("Ініціалізація бази даних SQLite...")
    await init_db()

    logger.info("Запуск Telegram-бота CO:LIVE...")
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Глобальний перехоплювач помилок
    @dp.error()
    async def global_error_handler(event: ErrorEvent):
        logger.error(f"Непередбачена помилка: {event.exception}", exc_info=True)
        if event.update and event.update.message:
            try:
                await event.update.message.answer(
                    "⚠️ Сталася неочікувана помилка під час обробки вашого запиту. Спробуйте ще раз або введіть /start."
                )
            except Exception:
                pass

    # Реєстрація мідлварів
    dp.message.middleware(AntiFloodMiddleware())
    dp.callback_query.middleware(AntiFloodMiddleware())

    # Реєстрація роутерів
    dp.include_router(start.router)
    dp.include_router(user_menu.router)
    dp.include_router(sotnik_panel.router)
    dp.include_router(group_chat.router)

    # Запуск щотижневого планувальника
    setup_scheduler(bot)

    logger.info(f"Запуск Web App сервера на http://{settings.WEBAPP_HOST}:{settings.WEBAPP_PORT}...")
    
    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            start_webapp()
        )
    except Exception as e:
        logger.error(f"Помилка роботи додатку: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Роботу CO:LIVE зупинено користувачем.")
