from sqlalchemy.ext.asyncio import AsyncSession

from payment_processing.domain.events.payment_requested import PaymentRequested
from payment_processing.infrastructure.repositories.models import OutboxRow


class SqlEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, event: PaymentRequested, route: str = "payments.new") -> None:
        self.session.add(
            OutboxRow(
                id=event.event_id,
                event_type="PaymentCreated.v1",
                payload={
                    "event_id": str(event.event_id),
                    "payment_id": str(event.payment_id),
                    "occurred_at": event.occurred_at.isoformat(),
                    "attempt": event.attempt,
                    "error": event.error,
                    "type": "PaymentCreated.v1",
                },
                route=route,
                created_at=event.occurred_at,
                available_at=event.occurred_at,
                published_at=None,
                publish_attempts=0,
            )
        )
        await self.session.flush()
