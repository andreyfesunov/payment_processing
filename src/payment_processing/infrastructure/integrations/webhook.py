from httpx import AsyncClient

from payment_processing.domain.abilities.payment import DeliverWebhookAbility
from payment_processing.domain.models.payment import Payment
from payment_processing.domain.models.types import JsonValue


class HttpWebhookSender:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def send(self, payment: Payment) -> None:
        DeliverWebhookAbility.check(payment.status).require()
        event_id = str(payment.id)
        payload: dict[str, JsonValue] = {
            "event_id": event_id,
            "payment_id": str(payment.id),
            "amount": format(payment.details.amount, ".2f"),
            "currency": payment.details.currency,
            "status": payment.status,
            "metadata": payment.details.metadata,
            "created_at": payment.created_at.isoformat(),
            "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
        }
        response = await self.client.post(
            payment.details.webhook_url,
            json=payload,
            headers={"Idempotency-Key": event_id},
            follow_redirects=False,
        )
        response.raise_for_status()
