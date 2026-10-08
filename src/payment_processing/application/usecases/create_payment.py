from payment_processing.application.ports.clock import Clock
from payment_processing.application.ports.transactions import DuplicatePaymentKey, UnitOfWorkFactory
from payment_processing.domain.models.payment import Payment, PaymentDetails


class CreatePayment:
    def __init__(self, transactions: UnitOfWorkFactory, clock: Clock) -> None:
        self.transactions = transactions
        self.clock = clock

    async def __call__(self, details: PaymentDetails, key: str) -> Payment:
        candidate = Payment.create(details, key, self.clock.now())
        try:
            async with self.transactions() as transaction:
                existing = await transaction.payments.get_by_key(key)
                if existing is not None:
                    return self._match(existing, candidate)
                await transaction.payments.add(candidate)
                for event in candidate.events:
                    await transaction.events.add(event)
                await transaction.commit()
                candidate.events.clear()
                return candidate
        except DuplicatePaymentKey:
            async with self.transactions() as transaction:
                existing = await transaction.payments.get_by_key(key)
                if existing is None:
                    raise RuntimeError("Conflicting payment was not found") from None
                return self._match(existing, candidate)

    @staticmethod
    def _match(existing: Payment, candidate: Payment) -> Payment:
        existing.ensure_same_request(candidate.request_fingerprint)
        return existing
