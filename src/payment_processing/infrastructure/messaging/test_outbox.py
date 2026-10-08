import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from faststream.rabbit import RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.domain.models.payment import PaymentDetails
from payment_processing.domain.models.types import Currency, JsonValue
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.messaging.outbox import OutboxPublisher, RabbitPublisher
from payment_processing.infrastructure.messaging.topology import NEW_QUEUE
from payment_processing.infrastructure.repositories.models import OutboxRow
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork

pytestmark = pytest.mark.integration


async def enqueue(sessions: async_sessionmaker[AsyncSession]) -> None:
    await CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())(
        PaymentDetails(Decimal("1"), Currency.RUB, "Order", {}, "https://example.com"), "key"
    )


async def test_publication_is_confirmed_and_marked_once(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    await enqueue(sessions)
    publisher = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    assert await publisher.run_once() == 1
    assert await publisher.run_once() == 0
    queue = await broker.declare_queue(NEW_QUEUE)
    message = await queue.get(timeout=2, fail=False)
    assert message is not None
    assert message.delivery_mode == 2
    async with sessions() as session:
        row = await session.scalar(select(OutboxRow))
        assert row is not None and row.published_at is not None
        assert message.message_id == str(row.id)
        assert row.publish_attempts == 1
    await message.ack()
    assert await queue.get(fail=False) is None


async def test_unroutable_event_is_retained_for_retry(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    await enqueue(sessions)
    queue = await broker.declare_queue(NEW_QUEUE)
    await queue.unbind("payments", routing_key="payments.new")
    try:
        publisher = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
        assert await publisher.run_once() == 0
        async with sessions() as session:
            row = await session.scalar(select(OutboxRow))
            assert row is not None
            assert row.published_at is None
            assert row.last_error is not None
            assert row.available_at > datetime.now(UTC)
        await queue.bind("payments", routing_key="payments.new")
        async with sessions.begin() as session:
            row = await session.scalar(select(OutboxRow))
            assert row is not None
            row.available_at = datetime.now(UTC)
        assert await publisher.run_once() == 1
    finally:
        await queue.bind("payments", routing_key="payments.new")


async def test_locked_outbox_rows_are_skipped(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    await enqueue(sessions)
    publisher = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    async with sessions.begin() as session:
        await session.scalar(select(OutboxRow).with_for_update())
        assert await asyncio.wait_for(publisher.run_once(), timeout=2) == 0
    assert await publisher.run_once() == 1


async def test_multiple_publishers_do_not_claim_the_same_row(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    await enqueue(sessions)
    first = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    second = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    assert sum(await asyncio.gather(first.run_once(), second.run_once())) == 1


class PublisherCrash(BaseException):
    pass


class CrashAfterPublish(RabbitPublisher):
    async def publish(self, payload: dict[str, JsonValue], route: str, event_id: str) -> None:
        await super().publish(payload, route, event_id)
        raise PublisherCrash


async def test_crash_after_publish_keeps_outbox_and_redelivers_same_event_id(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    await enqueue(sessions)
    crashing = OutboxPublisher(sessions, CrashAfterPublish(broker), SystemClock())
    with pytest.raises(PublisherCrash):
        await crashing.run_once()
    async with sessions() as session:
        row = await session.scalar(select(OutboxRow))
        assert row is not None
        assert row.published_at is None
        assert row.publish_attempts == 0
    recovered = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    assert await recovered.run_once() == 1
    queue = await broker.declare_queue(NEW_QUEUE)
    first = await queue.get(timeout=2)
    second = await queue.get(timeout=2)
    assert first is not None and second is not None
    assert first.message_id == second.message_id
    assert first.body == second.body
    await first.ack()
    await second.ack()
