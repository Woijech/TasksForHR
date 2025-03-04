import aiofiles
from uuid import uuid4
import logging
from openai import AsyncOpenAI
from sqlalchemy import select

from src.database.database import AsyncSessionLocal
from src.database.models import UserValue

logger = logging.getLogger(__name__)


async def get_user_values(user_id: int) -> list[str]:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserValue.value)
                .where(UserValue.user_id == user_id)
            )
            values = result.scalars().all()
            logger.info(f"Retrieved {len(values)} values for user {user_id}")
            return values
    except Exception as e:
        logger.error(f"Error in get_user_values: {e}")
        return []


async def save_value(user_id: int, value: str):
    try:
        async with AsyncSessionLocal() as session:
            new_value = UserValue(user_id=user_id, value=value)
            session.add(new_value)
            await session.commit()
            logger.info(f"Ценность '{value}' сохранена в базу данных для пользователя {user_id}.")
    except Exception as e:
        logger.error(f"Error in save_value: {e}")
        raise


class OpenAIBot:
    def __init__(self, api_key: str, assistant_id: str = None):
        self.client = AsyncOpenAI(api_key=api_key)
        self.user_threads = {}
        self.assistant_id = assistant_id
        logger.info("OpenAIBot initialized with API key")
        logger.info(f"Assistant ID: {self.assistant_id}")

    async def voice_to_text(self, audio_file_path):
        try:
            async with aiofiles.open(audio_file_path, "rb") as audio_file:
                content = await audio_file.read()
                transcript = await self.client.audio.transcriptions.create(
                    file=("voice_message.ogg", content, "audio/ogg"),
                    model="whisper-1",
                )
                logger.info("Voice message successfully transcribed")
            return transcript.text
        except Exception as e:
            logger.error(f"Error in transcribing audio: {e}")
            raise

    async def get_answer(self, user_id: int, prompt: str):
        try:
            if user_id not in self.user_threads:
                thread = await self.client.beta.threads.create()
                self.user_threads[user_id] = thread.id
                logger.info(f"Created new thread for user {user_id}: {thread.id}")
            else:
                thread_id = self.user_threads[user_id]
                logger.info(f"Using existing thread for user {user_id}: {thread_id}")

            await self.client.beta.threads.messages.create(
                thread_id=self.user_threads[user_id],
                role="user",
                content=prompt,
            )
            logger.info(f"Message added to thread for user {user_id}")

            if not self.assistant_id:
                raise Exception("Assistant ID is not set. Please create the assistant first.")

            response = await self.client.beta.threads.runs.create_and_poll(
                thread_id=self.user_threads[user_id],
                assistant_id=self.assistant_id,
                instructions="""Ты — помощник, который помогает человеку определить его ключевые жизненные ценности. Твоя задача — задавать вопросы, чтобы понять, что важно для человека, и помочь ему сформулировать свои ценности.

Вот как ты должен действовать:
1. Всегда начинай диалог с приветствия и вопроса о ценностях. Например: "Привет! Что для тебя самое важное в жизни?"
2. Если пользователь начинает с приветствия (например, "Привет, как дела?"), ответь на приветствие, но сразу переходи к вопросам о ценностях. Например: "Привет! У меня всё отлично, спасибо! А что для тебя самое важное в жизни?"
3. Анализируй ответы пользователя и уточняй, если что-то непонятно.
4. Продолжай задавать вопросы, чтобы узнать больше о ценностях пользователя.

Пример диалога:
- Пользователь: Привет!
- Ты: Привет! Что для тебя самое важное в жизни?
- Пользователь: Семья.
- Ты: Отлично! Что ещё важно для тебя какие у тебя хоби и тд?"""
            )
            logger.info(f"Run started for user {user_id}: {response.id}")

            if response.status == "completed":
                messages = await self.client.beta.threads.messages.list(
                    thread_id=self.user_threads[user_id],
                )
                for message in messages.data:
                    if message.role == "assistant":
                        assistant_message = message.content[0].text.value
                        logger.info(f"Received answer for user {user_id}: {assistant_message}")
                        return assistant_message

                logger.warning("No assistant message found in the thread.")
                return "Sorry, I couldn't generate a response."

            elif response.status in ["failed", "cancelled"]:
                logger.warning(f"Run failed or was cancelled: {response.status}")
                return "Sorry, I couldn't process your request."

            else:
                logger.warning(f"Unexpected run status: {response.status}")
                return "Sorry, something went wrong."

        except Exception as e:
            logger.error(f"Error in get_answer: {e}", exc_info=True)
            return "An error occurred while processing your request."

    async def text_to_voice(self, answer: str):
        try:
            unique_id = uuid4().hex
            output_file = f"response_{unique_id}.mp3"
            response = await self.client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=answer,
            )
            async with aiofiles.open(output_file, "wb") as f:
                await f.write(response.content)

            logger.info(f"Text to voice conversion successful ")
            return output_file
        except Exception as e:
            logger.error(f"Error in text_to_voice: {e}")
            raise

    async def validate_value(self, value: str) -> dict:
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Ты помогаешь пользователю определять его ключевые ценности. Проверь, является ли текст  ценностью.
                Ценность — это то, что важно для человека в жизни, например: семья, свобода, здоровье, карьера, дружба, саморазвитие.
                Ответь в формате JSON, содержащем два поля:
                - "is_valid": true или false (является ли текст ценностью)
                - "value_type": строка с типом ценности (если is_valid=true, иначе null).
                Примеры:
                - "Семья для меня важнее всего" → {"is_valid": true, "value_type": "семья"}
                - "Я ценю свободу" → {"is_valid": true, "value_type": "свобода"}
                - "Мне нравится заниматься спортом" → {"is_valid": true, "value_type": "здоровье"}
                - "Я устал" → {"is_valid": false, "value_type": null}
                """
                    }
                    ,
                    {
                        "role": "user",
                        "content": f"Это осмысленная ценность? {value}"
                    }
                ],
                response_format={"type": "json_object"},
            )
            response_json = response.choices[0].message.content
            logger.info(f"Response JSON: {response_json}")

            import json
            response_data = json.loads(response_json)
            return {
                "is_valid": response_data.get("is_valid", False),
                "value_type": response_data.get("value_type", None),
            }
        except Exception as e:
            logger.error(f"Error in validate_value: {e}")
            return {"is_valid": False, "value_type": None}
