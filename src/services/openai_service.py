import aiofiles
from pathlib import Path
from uuid import uuid4
import logging
from openai import AsyncOpenAI
import asyncio

logger = logging.getLogger(__name__)


class OpenAIBot:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.user_threads = {}
        self.assistant_id = None

        logger.info("OpenAIBot initialized with API key")

    async def create_assistant(self):
        """
        Создаем ассистента с инструкциями
        """
        try:
            assistant = await self.client.beta.assistants.create(
                name="Helper",
                instructions="You need to help person with his problem or just talk to person",
                model="gpt-4o",
            )
            self.assistant_id = assistant.id
            logger.info(f"Assistant created with ID: {self.assistant_id}")
        except Exception as e:
            logger.error(f"Error in creating assistant: {e}")

    async def voice_to_text(self, file_id, bot):
        ogg_file_name = Path(f"voice_message_{file_id}.ogg")

        try:
            file = await bot.get_file(file_id)
            downloaded_file = await bot.download_file(file.file_path)
            async with aiofiles.open(ogg_file_name, "wb") as f:
                await f.write(downloaded_file.read())
            logger.info(f"File saved as {ogg_file_name}")
            async with aiofiles.open(ogg_file_name, "rb") as audio_file:
                audio_content = await audio_file.read()
                transcript = await self.client.audio.transcriptions.create(
                    file=("voice_message.ogg", audio_content, "audio/ogg"),
                    model="whisper-1",
                )
                logger.info("Voice message successfully transcribed")
                return transcript.text

        except Exception as e:
            logger.error(f"Error in voice_to_text: {e}", exc_info=True)
            raise
        finally:
            if ogg_file_name.exists():
                ogg_file_name.unlink()
                logger.info(f"Temp file {ogg_file_name} removed")

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
                instructions="You are solving a math problem."
            )
            logger.info(f"Run started for user {user_id}: {response.id}")

            while True:
                run_status = await self.client.beta.threads.runs.retrieve(
                    thread_id=self.user_threads[user_id],
                    run_id=response.id,
                )
                if run_status.status == "completed":
                    break
                elif run_status.status in ["failed", "cancelled"]:
                    logger.warning(f"Run failed or was cancelled: {run_status.status}")
                    return "Sorry, I couldn't process your request."
                logger.info(f"Run status for user {user_id}: {run_status.status}")
                await asyncio.sleep(1)

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

        except Exception as e:
            logger.error(f"Error in get_answer: {e}", exc_info=True)
            return "An error occurred while processing your request."

    # async def get_answer(self, user_id: int, prompt: str):
    #     """
    #     Получаем ответ от ассистента с использованием Assistant API
    #     для конкретного пользователя
    #     """
    #     try:
    #         if user_id not in self.user_threads:
    #             thread = await self.client.beta.threads.create()
    #             self.user_threads[user_id] = thread.id
    #             logger.info(f"Created new thread for user {user_id}: {thread.id}")
    #         else:
    #             thread_id = self.user_threads[user_id]
    #             logger.info(f"Using existing thread for user {user_id}: {thread_id}")
    #         await self.client.beta.threads.messages.create(
    #             thread_id=self.user_threads[user_id],
    #             role="user",
    #             content=prompt,
    #         )
    #         logger.info(f"Message added to thread for user {user_id}")
    #
    #         if not self.assistant_id:
    #             raise Exception("Assistant ID is not set. Please create the assistant first.")
    #
    #         run = await self.client.beta.threads.runs.create(
    #             thread_id=self.user_threads[user_id],
    #             assistant_id=self.assistant_id,
    #         )
    #         logger.info(f"Run started for user {user_id}: {run.id}")
    #
    #         while True:
    #             run_status = await self.client.beta.threads.runs.retrieve(
    #                 thread_id=self.user_threads[user_id],
    #                 run_id=run.id,
    #             )
    #             if run_status.status == "completed":
    #                 break
    #             elif run_status.status in ["failed", "cancelled"]:
    #                 logger.warning(f"Run failed or was cancelled: {run_status.status}")
    #                 return "Sorry, I couldn't process your request."
    #             await asyncio.sleep(2)
    #
    #         messages = await self.client.beta.threads.messages.list(
    #             thread_id=self.user_threads[user_id],
    #         )
    #         for message in messages.data:
    #             if message.role == "assistant":
    #                 assistant_message = message.content[0].text.value
    #                 logger.info(f"Received answer for user {user_id}: {assistant_message}")
    #                 return assistant_message
    #         logger.warning("No assistant message found in the thread.")
    #         return "Sorry, I couldn't generate a response."
    #
    #     except Exception as e:
    #         logger.error(f"Error in get_answer: {e}", exc_info=True)
    #         return "An error occurred while processing your request."

    # async def get_answer(self, prompt: str):
    #     try:
    #         self.context.append({"role": "user", "content": prompt})
    #         response = await self.client.chat.completions.create(
    #             model="gpt-4o",
    #             messages=self.context
    #         )
    #         assistant_message = response.choices[0].message.content
    #
    #         self.context.append({"role": "assistant", "content": assistant_message})
    #
    #         logger.info("Received answer from OpenAI")
    #         return assistant_message
    #
    #     except Exception as e:
    #         logger.error(f"Error in get_answer: {e}")
    #         raise

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
