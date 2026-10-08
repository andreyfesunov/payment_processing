from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.presentation.http.models.payments import (
    CreatePaymentRequest,
    PaymentAccepted,
    PaymentResponse,
)


def to_details(request: CreatePaymentRequest) -> PaymentDetails:
    return PaymentDetails(
        request.amount,
        request.currency,
        request.description,
        request.metadata,
        str(request.webhook_url),
    )


def to_accepted(payment: Payment) -> PaymentAccepted:
    return PaymentAccepted(
        payment_id=payment.id, status=payment.status, created_at=payment.created_at
    )


def to_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
        amount=payment.details.amount,
        currency=payment.details.currency,
        description=payment.details.description,
        metadata=payment.details.metadata,
        webhook_url=payment.details.webhook_url,
        processed_at=payment.processed_at,
    )
