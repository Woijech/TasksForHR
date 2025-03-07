import aiofiles
from uuid import uuid4
import logging
from openai import AsyncOpenAI
from src.database.services import save_value
import json

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

    async def validate_value(self, value: str) -> dict:
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """Ты помогаешь пользователю определять его ключевые ценности. Проверь, является ли текст ценностью.
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
                    },
                    {
                        "role": "user",
                        "content": f"Это осмысленная ценность? {value}"
                    }
                ],
            )
            response_text = response.choices[0].message.content
            logger.info(f"Response text: {response_text}")

            # Вручную извлекаем JSON из текста
            import json
            try:
                response_data = json.loads(response_text)
                return {
                    "is_valid": response_data.get("is_valid", False),
                    "value_type": response_data.get("value_type", None),
                }
            except json.JSONDecodeError:
                logger.error("Failed to decode JSON from response.")
                return {"is_valid": False, "value_type": None}

        except Exception as e:
            logger.error(f"Error in validate_value: {e}")
            return {"is_valid": False, "value_type": None}

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
                instructions="""
    "Ты — помощник, который помогает человеку определить его ключевые жизненные ценности. "
    "Если человек говорит фразу, которая может быть ценностью, используй инструмент validate_value, чтобы проверить её. "
    "Если validate_value подтверждает, что это ценность, используй инструмент save_value для сохранения её в базу. "
    "Если фраза не является ценностью, продолжай диалог без вызова save_value. "
    "Не спрашивай пользователя о технических деталях проверки — просто решай сам, когда звать функции.""",
                tools=[
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