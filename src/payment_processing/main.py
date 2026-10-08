import argparse
import asyncio
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from types import FrameType

import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from payment_processing.application.consumers.payment_requested import PaymentRequestedConsumer
from payment_processing.application.ports.transactions import UnitOfWork
from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.config.logging import configure_logging
from payment_processing.infrastructure.config.settings import Settings
from payment_processing.infrastructure.integrations.gateway import EmulatedGateway
from payment_processing.infrastructure.integrations.webhook import HttpWebhookSender
from payment_processing.infrastructure.messaging.consumer import RabbitPaymentConsumer
from payment_processing.infrastructure.messaging.outbox import OutboxPublisher, RabbitPublisher
from payment_processing.infrastructure.messaging.topology import create_broker, declare_topology
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
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("api", "consumer", "outbox"), default="api", nargs="?")
    role: str = parser.parse_args().role
    configure_logging()
    if role == "api":
        uvicorn.run("payment_processing.main:create_api", factory=True, host="0.0.0.0", port=8000)
    else:
        asyncio.run(run_worker(role))


async def run_worker(role: str) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    broker = create_broker(settings.rabbitmq_url)
    clock = SystemClock()
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stop(signum: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(shutdown.set)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    publisher_task: asyncio.Task[None] | None = None
    try:
        async with AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
            if role == "consumer":
                RabbitPaymentConsumer(
                    broker,
                    PaymentRequestedConsumer(
                        lambda: SqlUnitOfWork(sessions),
                        EmulatedGateway(),
                        HttpWebhookSender(client),
                        clock,
                    ),
                )
            await broker.connect()
            await declare_topology(broker)
            if role == "consumer":
                await broker.start()
            else:
                publisher = OutboxPublisher(
                    sessions,
                    RabbitPublisher(broker),
                    clock,
                    settings.outbox_batch_size,
                    settings.outbox_poll_seconds,
                )
                publisher_task = asyncio.create_task(publisher.run_forever())
            try:
                await shutdown.wait()
            finally:
                if publisher_task is not None:
                    publisher_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await publisher_task
                await broker.stop()
    finally:
        await engine.dispose()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
