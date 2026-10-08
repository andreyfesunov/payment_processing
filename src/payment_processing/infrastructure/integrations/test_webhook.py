import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus
from payment_processing.infrastructure.integrations.webhook import HttpWebhookSender


def payment() -> Payment:
    result = Payment.create(
        PaymentDetails(Decimal("12.50"), Currency.USD, "Order", {}, "https://example.com/hook"),
        "key",
        datetime.now(UTC),
    )
    result.complete(PaymentStatus.SUCCEEDED, datetime.now(UTC))
    return result


async def test_payload_and_idempotency_key_stay_identical_on_redelivery() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    original = payment()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=5) as client:
        sender = HttpWebhookSender(client)
        await sender.send(original)
        await sender.send(original)
    assert requests[0].content == requests[1].content
    assert requests[0].headers["Idempotency-Key"] == str(original.id)
    assert requests[1].headers["Idempotency-Key"] == str(original.id)
    body = json.loads(requests[0].content)
    assert body["amount"] == "12.50"
    assert body["status"] == "succeeded"
    assert body["event_id"] == str(original.id)
    assert body["processed_at"] is not None


@pytest.mark.parametrize("status", [301, 400, 404, 429, 500, 503])
async def test_non_success_response_is_an_error_without_redirect(status: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://elsewhere.example"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=5) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await HttpWebhookSender(client).send(payment())
    assert len(requests) == 1


async def test_timeout_propagates_for_retry() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout), timeout=5) as client:
        with pytest.raises(httpx.ReadTimeout):
            await HttpWebhookSender(client).send(payment())
