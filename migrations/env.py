import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from logging.config import fileConfig

# Импортируйте ваши модели или Base
from src.database.models import Base # Замените на ваш Base или модели

config = context.config
fileConfig(config.config_file_name)

# URL базы данных из alembic.ini
url = config.get_main_option("sqlalchemy.url")
engine = create_async_engine(url)

# Асинхронная функция для запуска миграций
async def run_migrations_online():
    async with engine.connect() as connection:
        await connection.run_sync(lambda sync_conn: context.configure(
            connection=sync_conn,
            target_metadata=Base.metadata,  # Указываем ваши метаданные
            compare_type=True,
        ))

        # Исправленный вызов run_migrations
        await connection.run_sync(lambda sync_conn: context.run_migrations())
# Запуск асинхронного кода
loop = asyncio.get_event_loop()
loop.run_until_complete(run_migrations_online())