from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_ASSISTANT_ID: str | None = None

    class Config:
        env_file = '../.env'
        env_file_encoding = "utf-8"


settings = Settings()