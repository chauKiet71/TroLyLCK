from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from memory_bot.bot import MemoryBot
from memory_bot.config import get_settings
from memory_bot.database import Database
from memory_bot.schema import ensure_schema
from memory_bot.services.ai import AIService
from memory_bot.services.memory import MemoryService
from memory_bot.services.storage import LocalStorage


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    await ensure_schema(settings.database_url)
    database = Database(settings.database_url)
    await database.open()

    ai = AIService(
        settings.openai_api_key,
        settings.openai_chat_model,
        settings.openai_embedding_model,
    )
    memory_service = MemoryService(database, ai)
    application = MemoryBot(
        settings,
        database,
        ai,
        memory_service,
        LocalStorage(settings.storage_dir),
    )
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(application.router)

    try:
        await dispatcher.start_polling(bot)
    finally:
        await database.close()


def run() -> None:
    # Psycopg async requires a selector-based loop on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())


if __name__ == "__main__":
    run()
