import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.domain.errors.payment import IdempotencyConflict, PaymentNotFound
from payment_processing.domain.models.payment import PaymentDetails
from payment_processing.domain.models.types import Currency
from payment_processing.infrastructure.config.clock import SystemClock
from payment_processing.infrastructure.repositories.models import OutboxRow, PaymentRow
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork

pytestmark = pytest.mark.integration


def details(amount: str = "10.50") -> PaymentDetails:
    return PaymentDetails(Decimal(amount), Currency.USD, "Order", {}, "https://example.com/hook")


async def test_concurrent_identical_requests_create_one_payment_and_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    create = CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())
    payments = await asyncio.gather(*(create(details(), "same-key") for _ in range(10)))
    assert len({payment.id for payment in payments}) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentRow)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxRow)) == 1


async def test_conflicting_request_preserves_original(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    create = CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())
    original = await create(details(), "key")
    with pytest.raises(IdempotencyConflict):
        await create(details("11"), "key")
    assert await GetPayment(lambda: SqlUnitOfWork(sessions))(original.id) == original
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(OutboxRow)) == 1


async def test_concurrent_conflicting_requests_have_one_winner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    create = CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())
    results = await asyncio.gather(
        create(details("1"), "key"), create(details("2"), "key"), return_exceptions=True
    )
    assert sum(isinstance(result, IdempotencyConflict) for result in results) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentRow)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxRow)) == 1


async def test_equivalent_decimal_representation_returns_original(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    create = CreatePayment(lambda: SqlUnitOfWork(sessions), SystemClock())
    original = await create(details("10.5"), "key")
    replay = await create(details("10.50"), "key")
    assert replay.id == original.id
    assert replay.created_at == original.created_at


async def test_missing_payment_raises_domain_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(PaymentNotFound):
        await GetPayment(lambda: SqlUnitOfWork(sessions))(uuid4())
