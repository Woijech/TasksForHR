from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    OPENAI_API_KEY: str
    OPENAI_ASSISTANT_ID: str
    OPENAI_AMPLITUDE_KEY: str

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str
    REDIS_DB: int

    # MySQL
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_DATABASE: str
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    class Config:
        env_file = '../.env'
        env_file_encoding = "utf-8"


settings = Settings()