import aiofiles
from uuid import uuid4
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


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
                instructions="You are solving a math problem."
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
