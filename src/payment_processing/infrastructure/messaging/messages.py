from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from payment_processing.domain.events.payment_requested import PaymentRequested


class PaymentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["PaymentCreated.v1"]
    event_id: UUID
    payment_id: UUID
    occurred_at: AwareDatetime
    attempt: int = Field(ge=1, le=3)
    error: str | None = None

    def to_domain(self) -> PaymentRequested:
        return PaymentRequested(
            self.event_id, self.payment_id, self.occurred_at, self.attempt, self.error
        )
