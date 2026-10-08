from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from payment_processing.application.ports.transactions import UnitOfWork
from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.config.settings import Settings
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork
from payment_processing.presentation.http.app import create_http_app
from payment_processing.version import read_version


def create_api(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    engine = create_async_engine(config.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def transactions() -> UnitOfWork:
        return SqlUnitOfWork(sessions)

    async def check_database() -> None:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await engine.dispose()

    return create_http_app(
        CreatePayment(transactions, SystemClock()),
        GetPayment(transactions),
        config.api_key.get_secret_value(),
        read_version(),
        check_database,
        lifespan,
    )


def main() -> None:
    uvicorn.run("payment_processing.main:create_api", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
