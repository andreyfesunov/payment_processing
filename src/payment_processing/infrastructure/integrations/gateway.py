import asyncio
import hashlib
import random
from collections.abc import Awaitable, Callable

from payment_processing.domain.models.payment import Payment
from payment_processing.domain.models.types import PaymentStatus


class EmulatedGateway:
    def __init__(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.sleep = sleep
        self.random = random.SystemRandom()

    async def process(self, payment: Payment) -> PaymentStatus:
        await self.sleep(self.random.uniform(2, 5))
        value = int.from_bytes(hashlib.sha256(payment.id.bytes).digest(), "big")
        return PaymentStatus.FAILED if value % 10 == 0 else PaymentStatus.SUCCEEDED
