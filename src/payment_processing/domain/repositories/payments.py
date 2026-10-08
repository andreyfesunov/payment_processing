from typing import Protocol
from uuid import UUID

from payment_processing.domain.models.payment import Payment


class PaymentRepository(Protocol):
    async def get(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None: ...

    async def get_by_key(self, key: str) -> Payment | None: ...

    async def add(self, payment: Payment) -> None: ...

    async def save(self, payment: Payment) -> None: ...
