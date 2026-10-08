from types import TracebackType
from typing import Protocol, Self

from payment_processing.domain.events.payment_requested import PaymentRequested
from payment_processing.domain.repositories.payments import PaymentRepository


class DuplicatePaymentKey(Exception):
    pass


class EventRepository(Protocol):
    async def add(self, event: PaymentRequested, route: str = "payments.new") -> None: ...


class UnitOfWork(Protocol):
    payments: PaymentRepository
    events: EventRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
