import asyncio
import logging
from datetime import timedelta

from faststream.rabbit import RabbitBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.application.ports.clock import Clock
from payment_processing.domain.models.types import JsonValue
from payment_processing.infrastructure.messaging.topology import DEAD, PAYMENTS, RETRY
from payment_processing.infrastructure.repositories.models import OutboxRow

logger = logging.getLogger(__name__)


class RabbitPublisher:
    def __init__(self, broker: RabbitBroker) -> None:
        self.broker = broker

    async def publish(self, payload: dict[str, JsonValue], route: str, event_id: str) -> None:
        exchanges = {
            "payments.new": PAYMENTS,
            "payments.retry.2s": RETRY,
            "payments.retry.4s": RETRY,
            "payments.dlq": DEAD,
        }
        confirmation = await self.broker.publish(
            payload,
            exchange=exchanges[route],
            routing_key=route,
            persist=True,
            mandatory=True,
            timeout=5,
            message_id=event_id,
        )
        if confirmation is None or confirmation.name != "Basic.Ack":
            raise RuntimeError("RabbitMQ did not acknowledge publication")


class OutboxPublisher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        publisher: RabbitPublisher,
        clock: Clock,
        batch_size: int = 50,
        poll_seconds: float = 0.5,
    ) -> None:
        self.sessions = sessions
        self.publisher = publisher
        self.clock = clock
        self.batch_size = batch_size
        self.poll_seconds = poll_seconds

    async def run_once(self) -> int:
        async with self.sessions.begin() as session:
            rows = await session.scalars(
                select(OutboxRow)
                .where(OutboxRow.published_at.is_(None), OutboxRow.available_at <= self.clock.now())
                .order_by(OutboxRow.available_at, OutboxRow.created_at)
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
            )
            published = 0
            for row in rows:
                row.publish_attempts += 1
                try:
                    await self.publisher.publish(row.payload, row.route, str(row.id))
                except Exception as error:
                    row.last_error = type(error).__name__
                    row.available_at = self.clock.now() + timedelta(
                        seconds=min(2 ** min(row.publish_attempts, 6), 60)
                    )
                    logger.warning("outbox_publish_failed", extra={"event_id": str(row.id)})
                else:
                    row.published_at = self.clock.now()
                    row.last_error = None
                    published += 1
                    logger.info("outbox_published", extra={"event_id": str(row.id)})
            return published

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("outbox_cycle_failed")
            await asyncio.sleep(self.poll_seconds)
