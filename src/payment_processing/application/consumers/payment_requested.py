import logging
from dataclasses import replace
from uuid import uuid4

from payment_processing.application.ports.clock import Clock
from payment_processing.application.ports.payments import PaymentGateway, WebhookSender
from payment_processing.application.ports.transactions import EventRepository, UnitOfWorkFactory
from payment_processing.domain.errors.payment import PaymentNotFound
from payment_processing.domain.events.payment_requested import PaymentRequested

logger = logging.getLogger(__name__)


class PaymentRequestedConsumer:
    def __init__(
        self,
        transactions: UnitOfWorkFactory,
        gateway: PaymentGateway,
        webhook: WebhookSender,
        clock: Clock,
    ) -> None:
        self.transactions = transactions
        self.gateway = gateway
        self.webhook = webhook
        self.clock = clock

    async def __call__(self, event: PaymentRequested) -> None:
        async with self.transactions() as transaction:
            payment = await transaction.payments.get(event.payment_id, for_update=True)
            if payment is None:
                raise PaymentNotFound("Payment referenced by the event was not found")
            if not payment.can_handle(event.attempt):
                return
            if payment.needs_processing:
                try:
                    status = await self.gateway.process(payment)
                except Exception as error:
                    payment.finish_attempt(event.attempt, self.clock.now(), type(error).__name__)
                    await transaction.payments.save(payment)
                    await self._schedule(transaction.events, payment.can_retry, event, error)
                    await transaction.commit()
                    return
                payment.complete(status, self.clock.now())
                await transaction.payments.save(payment)
            await transaction.commit()

        async with self.transactions() as transaction:
            payment = await transaction.payments.get(event.payment_id, for_update=True)
            if payment is None:
                raise PaymentNotFound("Payment referenced by the event was not found")
            if not payment.can_handle(event.attempt):
                return
            try:
                await self.webhook.send(payment)
            except Exception as error:
                payment.finish_attempt(event.attempt, self.clock.now(), type(error).__name__)
                await transaction.payments.save(payment)
                await self._schedule(transaction.events, payment.can_retry, event, error)
                logger.warning(
                    "payment_attempt_failed",
                    extra={"payment_id": str(payment.id), "attempt": event.attempt},
                )
            else:
                payment.finish_attempt(event.attempt, self.clock.now())
                await transaction.payments.save(payment)
                logger.info("payment_notified", extra={"payment_id": str(payment.id)})
            await transaction.commit()

    async def _schedule(
        self,
        events: EventRepository,
        can_retry: bool,
        event: PaymentRequested,
        error: Exception,
    ) -> None:
        if can_retry:
            retry = event.retry(self.clock.now(), type(error).__name__)
            await events.add(retry, f"payments.retry.{2**event.attempt}s")
        else:
            dead = replace(
                event, event_id=uuid4(), occurred_at=self.clock.now(), error=type(error).__name__
            )
            await events.add(dead, "payments.dlq")
