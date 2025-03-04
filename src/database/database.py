from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.database.models import Base

# URL для SQLite
DATABASE_URL = "sqlite+aiosqlite:///./user_values.db"

# Создаем асинхронный движок
engine = create_async_engine(DATABASE_URL, echo=True)

# Создаем асинхронную сессию
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

async def init_db():
    """Инициализация базы данных (создание таблиц)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)