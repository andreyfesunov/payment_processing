import asyncio

from alembic import context
from pydantic import SecretStr
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from payment_processing.infrastructure.config.settings import Settings
from payment_processing.infrastructure.repositories.models import Base


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    settings = Settings(api_key=SecretStr("migration"))
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=Settings(api_key=SecretStr("migration")).database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
