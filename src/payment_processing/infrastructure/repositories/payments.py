from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payment_processing.application.ports.transactions import DuplicatePaymentKey
from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus
from payment_processing.infrastructure.repositories.models import PaymentRow


def to_payment(row: PaymentRow) -> Payment:
    return Payment(
        id=row.id,
        details=PaymentDetails(
            row.amount, Currency(row.currency), row.description, row.metadata_json, row.webhook_url
        ),
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        status=PaymentStatus(row.status),
        created_at=row.created_at,
        processed_at=row.processed_at,
        webhook_delivered_at=row.webhook_delivered_at,
        completed_attempts=row.completed_attempts,
        last_error=row.last_error,
    )


class SqlPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        query = select(PaymentRow).where(PaymentRow.id == payment_id)
        if for_update:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        return to_payment(row) if row is not None else None

    async def get_by_key(self, key: str) -> Payment | None:
        row = await self.session.scalar(select(PaymentRow).where(PaymentRow.idempotency_key == key))
        return to_payment(row) if row is not None else None

    async def add(self, payment: Payment) -> None:
        self.session.add(
            PaymentRow(
                id=payment.id,
                amount=payment.details.amount,
                currency=payment.details.currency,
                description=payment.details.description,
                metadata_json=payment.details.metadata,
                status=payment.status,
                idempotency_key=payment.idempotency_key,
                request_fingerprint=payment.request_fingerprint,
                webhook_url=payment.details.webhook_url,
                created_at=payment.created_at,
                processed_at=payment.processed_at,
                completed_attempts=payment.completed_attempts,
                webhook_delivered_at=payment.webhook_delivered_at,
                last_error=payment.last_error,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as error:
            if "payments_idempotency_key_key" in str(error.orig):
                raise DuplicatePaymentKey from error
            raise

    async def save(self, payment: Payment) -> None:
        row = await self.session.get(PaymentRow, payment.id)
        if row is None:
            raise LookupError(f"Payment disappeared: {payment.id}")
        row.status = payment.status
        row.processed_at = payment.processed_at
        row.webhook_delivered_at = payment.webhook_delivered_at
        row.completed_attempts = payment.completed_attempts
        row.last_error = payment.last_error
        await self.session.flush()
