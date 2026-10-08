from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.presentation.http.mappers.payments import (
    to_accepted,
    to_details,
    to_response,
)
from payment_processing.presentation.http.models.payments import (
    CreatePaymentRequest,
    PaymentAccepted,
    PaymentResponse,
)


def payment_router(create_payment: CreatePayment, get_payment: GetPayment) -> APIRouter:
    router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

    @router.post("", status_code=202)
    async def create(
        request: CreatePaymentRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
    ) -> PaymentAccepted:
        return to_accepted(await create_payment(to_details(request), idempotency_key))

    @router.get("/{payment_id}")
    async def get(payment_id: UUID) -> PaymentResponse:
        return to_response(await get_payment(payment_id))

    return router
