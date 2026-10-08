from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus
from payment_processing.infrastructure.integrations.gateway import EmulatedGateway


async def test_gateway_delay_probability_and_result_stability() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = EmulatedGateway(sleep)
    payment = Payment.create(
        PaymentDetails(Decimal("1"), Currency.RUB, "Order", {}, "https://example.com"),
        "key",
        datetime.now(UTC),
    )
    statuses: list[PaymentStatus] = []
    for index in range(1000):
        payment.id = UUID(int=index)
        status = await gateway.process(payment)
        assert await gateway.process(payment) == status
        statuses.append(status)
    assert all(2 <= delay <= 5 for delay in delays)
    assert 850 <= statuses.count(PaymentStatus.SUCCEEDED) <= 950
