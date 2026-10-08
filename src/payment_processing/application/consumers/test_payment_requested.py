from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.consumers.payment_requested import PaymentRequestedConsumer
from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.domain.events.payment_requested import PaymentRequested
from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.messaging.messages import PaymentMessage
from payment_processing.infrastructure.repositories.models import OutboxRow
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork

pytestmark = pytest.mark.integration


class Gateway:
    def __init__(self, status: PaymentStatus = PaymentStatus.SUCCEEDED, failures: int = 0) -> None:
        self.status = status
        self.failures = failures
        self.calls = 0

    async def process(self, payment: Payment) -> PaymentStatus:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("Gateway unavailable")
        return self.status


class Webhook:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.statuses: list[PaymentStatus] = []

    async def send(self, payment: Payment) -> None:
        self.calls += 1
        self.statuses.append(payment.status)
        if self.calls <= self.failures:
            raise RuntimeError("Webhook unavailable")


async def new_event(sessions: async_sessionmaker[AsyncSession]) -> PaymentRequested:
    payment = await CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())(
        PaymentDetails(Decimal("1"), Currency.RUB, "Order", {}, "https://example.com"), "key"
    )
    return await event_for_route(sessions, "payments.new", payment.id.hex)


async def event_for_route(
    sessions: async_sessionmaker[AsyncSession], route: str, payment_id: str = ""
) -> PaymentRequested:
    async with sessions() as session:
        row = await session.scalar(select(OutboxRow).where(OutboxRow.route == route))
        assert row is not None
        event = PaymentMessage.model_validate(row.payload).to_domain()
        if payment_id:
            assert event.payment_id.hex == payment_id
        return event


@pytest.mark.parametrize("status", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED])
async def test_result_is_saved_and_duplicate_is_ignored(
    sessions: async_sessionmaker[AsyncSession],
    status: PaymentStatus,
) -> None:
    event = await new_event(sessions)
    gateway, webhook = Gateway(status), Webhook()
    handler = PaymentRequestedConsumer(
        lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()
    )
    await handler(event)
    await handler(event)
    payment = await GetPayment(lambda: SqlUnitOfWork(sessions))(event.payment_id)
    assert payment.status == status
    assert payment.processed_at is not None
    assert payment.webhook_delivered_at is not None
    assert payment.completed_attempts == 1
    assert gateway.calls == webhook.calls == 1
    assert webhook.statuses == [status]


async def test_webhook_failure_retries_without_reprocessing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    event = await new_event(sessions)
    gateway, webhook = Gateway(), Webhook(failures=1)
    handler = PaymentRequestedConsumer(
        lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()
    )
    await handler(event)
    first = await GetPayment(lambda: SqlUnitOfWork(sessions))(event.payment_id)
    assert first.status == PaymentStatus.SUCCEEDED
    assert first.webhook_delivered_at is None
    assert first.completed_attempts == 1
    retry = await event_for_route(sessions, "payments.retry.2s")
    assert retry.attempt == 2
    await handler(event)
    assert webhook.calls == 1
    await handler(retry)
    final = await GetPayment(lambda: SqlUnitOfWork(sessions))(event.payment_id)
    assert final.processed_at == first.processed_at
    assert final.webhook_delivered_at is not None
    assert gateway.calls == 1
    assert webhook.calls == 2


async def test_third_webhook_failure_creates_one_dlq_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    event = await new_event(sessions)
    gateway, webhook = Gateway(), Webhook(failures=3)
    handler = PaymentRequestedConsumer(
        lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()
    )
    for route in ("payments.retry.2s", "payments.retry.4s"):
        await handler(event)
        event = await event_for_route(sessions, route)
    await handler(event)
    await handler(event)
    dead = await event_for_route(sessions, "payments.dlq")
    assert dead.attempt == 3
    assert dead.error == "RuntimeError"
    payment = await GetPayment(lambda: SqlUnitOfWork(sessions))(event.payment_id)
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.completed_attempts == 3
    assert payment.webhook_delivered_at is None
    assert gateway.calls == 1
    assert webhook.calls == 3
    async with sessions() as session:
        assert len(list(await session.scalars(select(OutboxRow)))) == 4


async def test_transient_gateway_failure_can_recover(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    event = await new_event(sessions)
    gateway, webhook = Gateway(failures=1), Webhook()
    handler = PaymentRequestedConsumer(
        lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()
    )
    await handler(event)
    pending = await GetPayment(lambda: SqlUnitOfWork(sessions))(event.payment_id)
    assert pending.status == PaymentStatus.PENDING
    assert webhook.calls == 0
    await handler(await event_for_route(sessions, "payments.retry.2s"))
    assert gateway.calls == 2
    assert webhook.calls == 1


async def test_saved_gateway_result_survives_redelivery_before_webhook(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    event = await new_event(sessions)
    async with SqlUnitOfWork(sessions) as transaction:
        payment = await transaction.payments.get(event.payment_id, for_update=True)
        assert payment is not None
        payment.complete(PaymentStatus.FAILED, datetime.now(UTC))
        await transaction.payments.save(payment)
        await transaction.commit()
    gateway, webhook = Gateway(), Webhook()
    await PaymentRequestedConsumer(
        lambda: SqlUnitOfWork(sessions), gateway, webhook, SystemClock()
    )(event)
    assert gateway.calls == 0
    assert webhook.statuses == [PaymentStatus.FAILED]
