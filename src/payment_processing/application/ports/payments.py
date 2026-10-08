from typing import Protocol

from payment_processing.domain.models.payment import Payment
from payment_processing.domain.models.types import PaymentStatus


class PaymentGateway(Protocol):
    async def process(self, payment: Payment) -> PaymentStatus: ...


class WebhookSender(Protocol):
    async def send(self, payment: Payment) -> None: ...
