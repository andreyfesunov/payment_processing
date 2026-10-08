import asyncio
import logging

from faststream import AckPolicy
from faststream.rabbit import RabbitBroker, RabbitMessage
from faststream.rabbit.message import RabbitMessage as RawRabbitMessage
from pydantic import ValidationError

from payment_processing.application.consumers.payment_requested import PaymentRequestedConsumer
from payment_processing.domain.errors.payment import OperationNotAllowed, PaymentNotFound
from payment_processing.infrastructure.messaging.messages import PaymentMessage
from payment_processing.infrastructure.messaging.topology import NEW_QUEUE, PAYMENTS

logger = logging.getLogger(__name__)


async def decode_raw(message: RawRabbitMessage) -> bytes:
    return message.raw_message.body


class RabbitPaymentConsumer:
    def __init__(self, broker: RabbitBroker, handler: PaymentRequestedConsumer) -> None:
        self.handler = handler
        broker.subscriber(
            NEW_QUEUE,
            PAYMENTS,
            ack_policy=AckPolicy.MANUAL,
            decoder=decode_raw,
            no_reply=True,
        )(self.consume)

    async def consume(self, message: RabbitMessage) -> None:
        try:
            event = PaymentMessage.model_validate_json(message.raw_message.body).to_domain()
        except ValidationError:
            logger.warning("invalid_payment_event", extra={"event_id": message.message_id})
            await message.reject(requeue=False)
            return
        while True:
            try:
                await self.handler(event)
            except (PaymentNotFound, OperationNotAllowed):
                logger.warning(
                    "unprocessable_payment_event", extra={"event_id": str(event.event_id)}
                )
                await message.reject(requeue=False)
                return
            except Exception:
                logger.exception("payment_infrastructure_unavailable")
                await asyncio.sleep(2)
            else:
                await message.ack()
                return
