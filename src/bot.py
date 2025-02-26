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

openai_service = OpenAIBot(api_key=settings.OPENAI_API_KEY)

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, timeout=60.0)
dp = Dispatcher()

async def initialize_assistant():
    await openai_service.create_assistant()

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
        text = await openai_service.voice_to_text(message.voice.file_id, bot)
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
        await message.reply_audio(audio_reply,f'response for {message.from_user.username}')
    except Exception as e:
        logger.error(f"Error in handle_voice: {e}")
        await message.reply(f'Error: {e}')
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)
            logger.info(f"Temp file {audio_file} removed")


async def main():
    logger.info("Starting bot")
    await initialize_assistant()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
