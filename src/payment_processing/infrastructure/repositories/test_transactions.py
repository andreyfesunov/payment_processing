from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.ports.transactions import DuplicatePaymentKey
from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency
from payment_processing.infrastructure.repositories.models import OutboxRow, PaymentRow
from payment_processing.infrastructure.repositories.transactions import SqlUnitOfWork

pytestmark = pytest.mark.integration


def payment() -> Payment:
    return Payment.create(
        PaymentDetails(
            Decimal("12.34"), Currency.EUR, "Order", {"cart": [1]}, "https://example.com"
        ),
        "key",
        datetime.now(UTC),
    )


async def test_commit_persists_payment_and_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    original = payment()
    async with SqlUnitOfWork(sessions) as transaction:
        await transaction.payments.add(original)
        await transaction.events.add(original.events[0])
        await transaction.commit()
    async with SqlUnitOfWork(sessions) as transaction:
        restored = await transaction.payments.get(original.id)
        assert restored == original
    async with sessions() as session:
        event = await session.scalar(select(OutboxRow))
        assert event is not None
        assert event.payload["payment_id"] == str(original.id)
        assert event.published_at is None


async def test_exception_rolls_back_both_records(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    original = payment()
    with pytest.raises(RuntimeError, match="Abort"):
        async with SqlUnitOfWork(sessions) as transaction:
            await transaction.payments.add(original)
            await transaction.events.add(original.events[0])
            raise RuntimeError("Abort")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentRow)) == 0
        assert await session.scalar(select(func.count()).select_from(OutboxRow)) == 0


async def test_duplicate_key_is_translated_without_overwriting_payment(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    original = payment()
    async with SqlUnitOfWork(sessions) as transaction:
        await transaction.payments.add(original)
        await transaction.commit()
    with pytest.raises(DuplicatePaymentKey):
        async with SqlUnitOfWork(sessions) as transaction:
            await transaction.payments.add(payment())
            await transaction.commit()
    async with SqlUnitOfWork(sessions) as transaction:
        restored = await transaction.payments.get_by_key("key")
        assert restored is not None
        assert restored.id == original.id
