import aiofiles
from aiogram.types import FSInputFile
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from src.config import settings
from src.services.openai_service import OpenAIBot
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

openai_service = OpenAIBot(api_key=settings.OPENAI_API_KEY, assistant_id=settings.OPENAI_ASSISTANT_ID)

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, timeout=60.0)
dp = Dispatcher()


async def download_voice_file(file_id: str, file_name: str) -> str:
    """
    Скачивает голосовое сообщение и сохраняет его в файл.
    Возвращает путь к сохраненному файлу.
    """
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await bot.download_file(file_path)

        async with aiofiles.open(file_name, "wb") as f:
            await f.write(downloaded_file.read())

        logger.info(f"{file_name} successfully downloaded.")
        return file_name
    except Exception as e:
        logger.error(f"Error in downloading file: {e}")
        raise


@dp.message(Command("start"))
async def start(message: Message):
    try:
        await message.answer(
            f"Hello, {message.from_user.first_name}! Send me a voice or type /help to get started."
        )
        logger.info(f"Sent welcome message to {message.from_user.username}")
    except Exception as e:
        logger.error(f"Error in start command: {e}")


@dp.message(Command("help"))
async def help_command(message: Message):
    try:
        await message.answer(
            "This bot supports only voice messages. Please send a voice message with your question."
        )
        logger.info(f"Sent help message to {message.from_user.username}")
    except Exception as e:
        logger.error(f"Error in help command: {e}")


@dp.message(lambda message: message.voice is not None)
async def handle_voice(message: Message):
    try:
        file_id = message.voice.file_id
        ogg_file_name = f"voice_message_{file_id}.ogg"

        await download_voice_file(file_id, ogg_file_name)

        text = await openai_service.voice_to_text(ogg_file_name)
        if not text:
            await message.reply("Failed to recognize the voice.")
            logger.warning("Voice recognition failed")
            return
        response = await openai_service.get_answer(message.from_user.id, text)
        if not response:
            await message.reply("Failed to translate voice to text.")
            logger.warning("Voice to text translation failed")
            return
        audio_file = await openai_service.text_to_voice(response)
        audio_reply = FSInputFile(audio_file)
        logger.info(f"{type(audio_reply)}")
        await message.answer_voice(voice=audio_reply, caption="Here is your response!")
    except Exception as e:
        logger.error(f"Error in handle_voice: {e}")
        await message.reply(f'Error: {e}')
    finally:
        if ogg_file_name and os.path.exists(ogg_file_name):
            os.remove(ogg_file_name)
            logger.info(f"Временный файл {ogg_file_name} удален.")
        if os.path.exists(audio_file):
            os.remove(audio_file)
            logger.info(f"Temp file {audio_file} removed")


async def main():
    logger.info("Starting bot")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
