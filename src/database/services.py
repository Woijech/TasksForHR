from sqlalchemy import select

async def get_user_values(user_id: int) -> list[str]:
    from src.bot import logger
    from src.database.database import AsyncSessionLocal
    from src.database.models import UserValue
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
    from src.bot import logger
    from src.database.database import AsyncSessionLocal
    from src.database.models import UserValue
    try:
        async with AsyncSessionLocal() as session:
            new_value = UserValue(user_id=user_id, value=value)
            session.add(new_value)
            await session.commit()
            logger.info(f"Value '{value}' saved to the database for the user {user_id}.")
    except Exception as e:
        logger.error(f"Error in save_value: {e}")
        raise