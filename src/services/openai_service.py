import aiofiles
from uuid import uuid4
import logging

from aiogram.fsm.context import FSMContext
from openai import AsyncOpenAI
from src.database.services import save_value
import json
from amplitude import Amplitude, BaseEvent
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
amplitude_executor = ThreadPoolExecutor(max_workers=1)


class OpenAIBot:
    def __init__(self, api_key: str, assistant_id: str = None, amplitude_key: str = None):
        self.client = AsyncOpenAI(api_key=api_key)
        self.user_threads = {}
        self.assistant_id = assistant_id
        self.amplitude_client = Amplitude(api_key=amplitude_key)
        self.vector_store_id = None
        logger.info("OpenAIBot initialized with API key")
        logger.info(f"Assistant ID: {self.assistant_id}")

    async def create_vector_store(self, file_path: str, name: str = "Values Documents"):
        try:
            vector_store = await self.client.beta.vector_stores.create(
                name=name
            )
            self.vector_store_id = vector_store.id
            file = await self.client.beta.vector_stores.files.upload_and_poll(
                vector_store_id=vector_store.id,
                file=open(file_path, "rb")
            )

            logger.info(f"Created vector store {vector_store.id} with file {file.id}")
            return vector_store.id
        except Exception as e:
            logger.error(f"Error creating vector store: {e}", exc_info=True)
            raise

    async def update_assistant_with_file_search(self):
        if not self.assistant_id:
            raise ValueError("Assistant ID is not set")
        if not self.vector_store_id:
            raise ValueError("Vector store ID is not set")

        try:
            assistant = await self.client.beta.assistants.update(
                assistant_id=self.assistant_id,
                tools=[
                    {
                        "type": "file_search"
                    }
                ],
                tool_resources={
                    "file_search": {
                        "vector_store_ids": [self.vector_store_id]
                    }
                }
            )
            logger.info(f"Updated assistant {assistant.id} with file search capability")
            return assistant
        except Exception as e:
            logger.error(f"Error updating assistant: {e}", exc_info=True)
            raise

    async def analyze_mood_from_photo(self, image_url: str, user_id: int):
        try:
            amplitude_executor.submit(
                self.amplitude_client.track,
                BaseEvent(
                    event_type="photo_uploaded",
                    user_id=str(user_id),
                    event_properties={"image_url": image_url},
                ),
            )
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text",
                             "text": "Определи настроение человека на фото. Ответь одним словом: счастье, грусть, злость, нейтрально, удивление.Если не получится определить настроение верни сообщение Не удалось определить настроение."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_url}", }},
                        ],
                    }
                ],
                max_tokens=300,
            )
            mood = response.choices[0].message.content
            logger.info(f"Mood analysis result for user {user_id}: {mood}")
            amplitude_executor.submit(
                self.amplitude_client.track,
                BaseEvent(
                    event_type="photo_analyzed",
                    user_id=str(user_id),
                    event_properties={"mood": mood},
                ),
            )

            return mood
        except Exception as e:
            logger.error(f"Error in analyze_mood_from_photo: {e}", exc_info=True)
            amplitude_executor.submit(
                self.amplitude_client.track,
                BaseEvent(
                    event_type="photo_analysis_failed",
                    user_id=str(user_id),
                    event_properties={"error": str(e)},
                ),
            )
            return "Не удалось определить настроение."

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

    async def validate_value(self, value: str) -> dict:
        try:
            json_schema = {
                "name": "value_validation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "is_valid": {"type": "boolean"},
                        "value_type": {"type": "string"}
                    },
                    "required": ["is_valid", "value_type"],
                    "additionalProperties": False
                }
            }
            response = await self.client.chat.completions.create(
                model="gpt-4o-2024-08-06",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты помогаешь пользователю определять его ключевые ценности. "
                            "Ценность — это то, что важно для человека в жизни, например: "
                            "семья, свобода, здоровье, карьера, дружба, саморазвитие."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Это осмысленная ценность? {value}"
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": json_schema
                }
            )

            if hasattr(response, "choices") and response.choices:
                content = response.choices[0].message.content
                try:
                    validation_result = json.loads(content)
                except json.JSONDecodeError:
                    logger.error(f"[validate_value] Error in decoding JSON: {content}")
                    validation_result = {"is_valid": False, "value_type": None}
            else:
                logger.error("[validate_value] Invalid response format OpenAI API")
                validation_result = {"is_valid": False, "value_type": None}

            return validation_result

        except Exception as e:
            logger.error(f"Error in validate_value: {e}", exc_info=True)
            return {"is_valid": False, "value_type": None}

    async def get_answer(self, user_id: int, prompt: str, state: FSMContext):
        try:
            data = await state.get_data()
            thread_id = data.get('thread_id')

            if not thread_id:
                thread = await self.client.beta.threads.create()
                thread_id = thread.id
                await state.update_data(thread_id=thread_id)
                logger.info(f"Created new thread for user {user_id}: {thread_id}")
            else:
                logger.info(f"Using existing thread for user {user_id}: {thread_id}")

            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=prompt,
            )
            logger.info(f"Message added to thread for user {user_id}")

            if not self.assistant_id:
                raise Exception("Assistant ID is not set. Please create the assistant first.")

            response = await self.client.beta.threads.runs.create_and_poll(
                thread_id=self.user_threads[user_id],
                assistant_id=self.assistant_id,
                instructions="""
                    Ты — помощник, который помогает человеку определить его ключевые жизненные ценности.
                    Если человек говорит фразу, которая может быть ценностью, используй инструмент validate_value, чтобы проверить её.
                    Если validate_value подтверждает, что это ценность, используй инструмент save_value для сохранения её в базу.
                    Если фраза не является ценностью, продолжай диалог без вызова save_value.
                    Не спрашивай пользователя о технических деталях проверки — просто решай сам, когда звать функции.
                    При поиске информации в документах, всегда указывай название файла после цитаты.
                """,
                tools=[
                    {
                        "type": "file_search"
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "validate_value",
                            "description": "Проверяет, является ли данное значение ключевой ценностью.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": "string", "description": "Текст для проверки на ценность."}
                                },
                                "required": ["value"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "save_value",
                            "description": "Сохраняет подтверждённую ценность пользователя.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "user_id": {"type": "integer", "description": "ID пользователя."},
                                    "value": {"type": "string", "description": "Подтверждённая ключевая ценность."}
                                },
                                "required": ["user_id", "value"]
                            }
                        }
                    }
                ],

                tool_choice="auto"
            )
            logger.info(f"Run started for user {user_id}: {response.id}")

            if response.status == "requires_action":
                tool_calls = response.required_action.submit_tool_outputs.tool_calls
                tool_outputs = []

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    if function_name == "validate_value":
                        validation_result = await self.validate_value(function_args["value"])
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(validation_result),
                        })
                        if validation_result["is_valid"]:
                            await save_value(user_id=user_id, value=validation_result["value_type"])
                            logger.info(f"Value saved for user {user_id}: {validation_result['value_type']}")

                    elif function_name == "save_value":
                        await save_value(user_id=function_args["user_id"], value=function_args["value"])
                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps({"status": "success"}),
                        })

                await self.client.beta.threads.runs.submit_tool_outputs(
                    thread_id=self.user_threads[user_id],
                    run_id=response.id,
                    tool_outputs=tool_outputs
                )
                logger.info(f"Tool outputs submitted for run {response.id}")
                response = await self.client.beta.threads.runs.retrieve(
                    thread_id=self.user_threads[user_id],
                    run_id=response.id
                )

            if response.status == "completed":
                messages = await self.client.beta.threads.messages.list(
                    thread_id=self.user_threads[user_id],
                )
                for message in messages.data:
                    if message.role == "assistant":
                        if hasattr(message.content[0], 'text') and hasattr(message.content[0].text, 'annotations'):
                            annotations = message.content[0].text.annotations
                            for annotation in annotations:
                                if hasattr(annotation, 'file_path'):
                                    file_citation = getattr(annotation, 'file_citation', None)
                                    if file_citation:
                                        file_id = file_citation.file_id
                                        file_info = await self.client.files.retrieve(file_id)
                                        message.content[0].text.value = message.content[0].text.value.replace(
                                            annotation.text, f"[из файла: {file_info.filename}]"
                                        )

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

            logger.info(f"Text to voice conversion successful")
            return output_file
        except Exception as e:
            logger.error(f"Error in text_to_voice: {e}")
            raise
