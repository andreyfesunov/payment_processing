from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class PaymentRequested:
    event_id: UUID
    payment_id: UUID
    occurred_at: datetime
    attempt: int = 1
    error: str | None = None

    def retry(self, now: datetime, error: str) -> Self:
        return type(self)(uuid4(), self.payment_id, now, self.attempt + 1, error)
