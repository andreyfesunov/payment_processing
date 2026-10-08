import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+asyncpg://payments:payments@localhost:5432/payments_test"
    )
    database = make_url(url).database
    if database is None or re.fullmatch(r"[a-z_]+_test", database) is None:
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")

    async def provision() -> None:
        engine = create_async_engine(make_url(url).set(database="postgres"))
        try:
            async with engine.connect() as connection:
                connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
                exists = await connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
                )
                if not exists:
                    await connection.execute(text(f'CREATE DATABASE "{database}"'))
        finally:
            await engine.dispose()

    asyncio.run(provision())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DATABASE_URL": url},
        check=True,
    )
    return url


@pytest_asyncio.fixture
async def sessions(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE payments, outbox"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
