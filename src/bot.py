import aiofiles
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage import redis
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import FSInputFile
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from src.config import settings
from src.database.database import init_db
from src.database.services import get_user_values, save_value
from src.services.openai_service import OpenAIBot
import asyncio
import logging
import os
import base64
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
redis_connection = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
    db=settings.REDIS_DB
)
storage = RedisStorage(redis=redis_connection)
openai_service = OpenAIBot(api_key=settings.OPENAI_API_KEY, assistant_id=settings.OPENAI_ASSISTANT_ID,amplitude_key=settings.OPENAI_AMPLITUDE_KEY)

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, timeout=60.0)
dp = Dispatcher()


async def download_file(file_id: str, file_name: str) -> str:
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

async def image_to_base64(file_path: str) -> str:
    logger.info(f"Converting image to base64...")
    async with aiofiles.open(file_path, "rb") as f:
        file_content = await f.read()
        return base64.b64encode(file_content).decode("utf-8")
@dp.message(Command("start"))
async def start(message: Message):
    try:
        await message.answer(
            f"Hello, {message.from_user.first_name}! Send me"
            f""
            f" a voice or type /help to get started."
        )
        logger.info(f"Sent welcome message to {message.from_user.username}")
    except Exception as e:
        logger.error(f"Error in start command: {e}")


@dp.message(Command("help"))
async def help_command(message: Message):
    try:
        await message.answer(
            "This bot supports only voice messages. Please send a voice message with your question. Type /my_values to watch your values"
        )
        logger.info(f"Sent help message to {message.from_user.username}")

    except Exception as e:
        logger.error(f"Error in help command: {e}")
@dp.message(Command("my_values"))
async def show_user_values(message: Message):
    try:
        user_id = message.from_user.id
        values = await get_user_values(user_id)
        if values:
            values_text = "\n".join([f"• {value}" for value in values])
            await message.answer(f"Your saved valuables: \n{values_text}")
        else:
            await message.answer("You don't have any stored valuables yet.")
    except Exception as e:
        logger.error(f"Error in show_user_values: {e}")
        await message.answer(f'Error: {e}')


@dp.message(lambda message: message.voice is not None)
@dp.message(lambda message: message.voice is not None)
async def handle_voice(message: Message, state: FSMContext):
    try:
        file_id = message.voice.file_id
        ogg_file_name = f"voice_message_{file_id}.ogg"

        await download_file(file_id, ogg_file_name)

        text = await openai_service.voice_to_text(ogg_file_name)
        response = await openai_service.get_answer(message.from_user.id, text, state)
        audio_file = await openai_service.text_to_voice(response)
        audio_reply = FSInputFile(audio_file)
        logger.info(f"{type(audio_reply)}")
        await message.answer_voice(voice=audio_reply, caption="Here is your response!")
    except Exception as e:
        logger.error(f"Error in handle_voice: {e}")
        await message.reply(f'Error: {e}')
    finally:
        if 'ogg_file_name' in locals() and os.path.exists(ogg_file_name):
            os.remove(ogg_file_name)
            logger.info(f"Temporary file {ogg_file_name} removed .")
        if 'audio_file' in locals() and os.path.exists(audio_file):
            os.remove(audio_file)
            logger.info(f"Temp file {audio_file} removed")
@dp.message(lambda message: message.photo is not None)
async def handle_image(message: Message):
    try:
        file_id = message.photo[-1].file_id
        image_file_name = f"image_{file_id}.jpg"

        await download_file(file_id, image_file_name)
        image_base64 = await image_to_base64(image_file_name)
        mood = await openai_service.analyze_mood_from_photo(image_base64, message.from_user.id)
        if mood!='Не удалось определить настроение.':
         await message.answer(f"Настроение на фото: {mood}")
         await save_value(message.from_user.id, mood)
        else:
            await message.answer('Я не смог определить настроение на фото')
    except Exception as e:
        logger.error(f"Error in handle_image: {e}")
        await message.reply(f'Error: {e}')
    finally:
        if 'image_file_name' in locals() and os.path.exists(image_file_name):
            os.remove(image_file_name)
            logger.info(f"Temporary file {image_file_name} removed.")

async def main():
    await init_db()
    logger.info("Starting bot")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())