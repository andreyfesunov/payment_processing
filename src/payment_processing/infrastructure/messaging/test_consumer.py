import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.consumers.payment_requested import PaymentRequestedConsumer
from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.messaging.consumer import RabbitPaymentConsumer
from payment_processing.infrastructure.messaging.outbox import OutboxPublisher, RabbitPublisher
from payment_processing.infrastructure.messaging.topology import DLQ, NEW_QUEUE, PAYMENTS
from payment_processing.infrastructure.repositories.models import OutboxRow
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork

pytestmark = pytest.mark.integration


class Gateway:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, payment: Payment) -> PaymentStatus:
        self.calls += 1
        return PaymentStatus.SUCCEEDED


class Webhook:
    def __init__(self, failures: int = 0) -> None:
        self.calls = 0
        self.failures = failures

    async def send(self, payment: Payment) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("Unavailable")


async def wait_for_delivery(
    sessions: async_sessionmaker[AsyncSession],
    payment: Payment,
    publisher: OutboxPublisher,
) -> None:
    async with asyncio.timeout(12):
        while True:
            await publisher.run_once()
            current = await GetPayment(lambda: SqlUnitOfWork(sessions))(payment.id)
            if current.webhook_delivered_at is not None:
                return
            await asyncio.sleep(0.05)


async def test_real_consumer_acknowledges_payment_and_ignores_duplicate(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    gateway, webhook = Gateway(), Webhook()
    RabbitPaymentConsumer(
        broker,
        PaymentRequestedConsumer(lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()),
    )
    await broker.start()
    payment = await CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())(
        PaymentDetails(Decimal("1"), Currency.RUB, "Order", {}, "https://example.com"), "key"
    )
    publisher = OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    await wait_for_delivery(sessions, payment, publisher)
    async with sessions() as session:
        row = await session.scalar(select(OutboxRow))
        assert row is not None
        await RabbitPublisher(broker).publish(row.payload, row.route, str(row.id))
    await asyncio.sleep(0.2)
    assert gateway.calls == webhook.calls == 1
    queue = await broker.declare_queue(NEW_QUEUE)
    assert await queue.get(fail=False) is None


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"type":"Unknown.v1"}'])
async def test_malformed_message_is_dead_lettered(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
    body: bytes,
) -> None:
    RabbitPaymentConsumer(
        broker,
        PaymentRequestedConsumer(
            lambda: SqlUnitOfWork(sessions), Gateway(), Webhook(), SystemClock()
        ),
    )
    await broker.start()
    await broker.publish(body, exchange=PAYMENTS, routing_key=NEW_QUEUE.name, persist=True)
    queue = await broker.declare_queue(DLQ)
    async with queue.iterator(timeout=5) as messages:
        message = await anext(messages)
        assert message.body == body
        assert "x-death" in message.headers
        await message.ack()


async def test_missing_payment_is_dead_lettered(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    RabbitPaymentConsumer(
        broker,
        PaymentRequestedConsumer(
            lambda: SqlUnitOfWork(sessions), Gateway(), Webhook(), SystemClock()
        ),
    )
    await broker.start()
    await RabbitPublisher(broker).publish(
        {
            "type": "PaymentCreated.v1",
            "event_id": str(uuid4()),
            "payment_id": str(uuid4()),
            "occurred_at": SystemClock().now().isoformat(),
            "attempt": 1,
        },
        "payments.new",
        str(uuid4()),
    )
    queue = await broker.declare_queue(DLQ)
    async with queue.iterator(timeout=5) as messages:
        message = await anext(messages)
        await message.ack()


async def test_webhook_retry_uses_ttl_queue_and_preserves_payment_result(
    sessions: async_sessionmaker[AsyncSession],
    broker: RabbitBroker,
) -> None:
    gateway, webhook = Gateway(), Webhook(failures=1)
    RabbitPaymentConsumer(
        broker,
        PaymentRequestedConsumer(lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()),
    )
    await broker.start()
    payment = await CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())(
        PaymentDetails(Decimal("1"), Currency.RUB, "Order", {}, "https://example.com"), "key"
    )
    start = asyncio.get_running_loop().time()
    await wait_for_delivery(
        sessions, payment, OutboxPublisher(sessions, RabbitPublisher(broker), SystemClock())
    )
    assert asyncio.get_running_loop().time() - start >= 2
    assert gateway.calls == 1
    assert webhook.calls == 2
