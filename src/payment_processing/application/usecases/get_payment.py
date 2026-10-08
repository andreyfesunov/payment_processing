from uuid import UUID

from payment_processing.application.ports.transactions import UnitOfWorkFactory
from payment_processing.domain.errors.payment import PaymentNotFound
from payment_processing.domain.models.payment import Payment


class GetPayment:
    def __init__(self, transactions: UnitOfWorkFactory) -> None:
        self.transactions = transactions

    async def __call__(self, payment_id: UUID) -> Payment:
        async with self.transactions() as transaction:
            payment = await transaction.payments.get(payment_id)
            if payment is None:
                raise PaymentNotFound("Payment was not found")
            return payment
