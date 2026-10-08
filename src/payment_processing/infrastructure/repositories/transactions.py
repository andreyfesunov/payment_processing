from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.ports.transactions import EventRepository
from payment_processing.domain.repositories.payments import PaymentRepository
from payment_processing.infrastructure.repositories.outbox import SqlEventRepository
from payment_processing.infrastructure.repositories.payments import SqlPaymentRepository


class SqlUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session = session_factory()
        self.payments: PaymentRepository = SqlPaymentRepository(self.session)
        self.events: EventRepository = SqlEventRepository(self.session)

    async def __aenter__(self) -> Self:
        await self.session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()
