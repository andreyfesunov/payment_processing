import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

from payment_processing.domain.abilities.payment import (
    CompletePaymentAbility,
    CreatePaymentAbility,
    DeliverWebhookAbility,
    ProcessPaymentAbility,
    ReplayPaymentAbility,
    RetryPaymentAbility,
)
from payment_processing.domain.errors.payment import IdempotencyConflict, InvalidPayment
from payment_processing.domain.events.payment_requested import PaymentRequested
from payment_processing.domain.models.types import Currency, JsonValue, PaymentStatus


@dataclass(frozen=True, slots=True)
class PaymentDetails:
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, JsonValue]
    webhook_url: str

    def fingerprint(self) -> str:
        body = json.dumps(
            {
                "amount": format(self.amount.quantize(Decimal("0.01")), "f"),
                "currency": self.currency,
                "description": self.description,
                "metadata": self.metadata,
                "webhook_url": self.webhook_url,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(body.encode()).hexdigest()


@dataclass(slots=True)
class Payment:
    id: UUID
    details: PaymentDetails
    idempotency_key: str
    request_fingerprint: str
    status: PaymentStatus
    created_at: datetime
    processed_at: datetime | None = None
    webhook_delivered_at: datetime | None = None
    completed_attempts: int = 0
    last_error: str | None = None
    events: list[PaymentRequested] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def create(cls, details: PaymentDetails, key: str, now: datetime) -> Self:
        result = CreatePaymentAbility.check(details.amount)
        if not result.allowed:
            raise InvalidPayment(result.reason)
        if not key.strip() or len(key) > 255:
            raise InvalidPayment("Idempotency key must contain 1 to 255 characters")
        if not details.description or len(details.description) > 1000:
            raise InvalidPayment("Description must contain 1 to 1000 characters")
        payment = cls(uuid4(), details, key, details.fingerprint(), PaymentStatus.PENDING, now)
        payment.events.append(PaymentRequested(uuid4(), payment.id, now))
        return payment

    def complete(self, status: PaymentStatus, now: datetime) -> None:
        CompletePaymentAbility.check(self.status, status).require()
        self.status = status
        self.processed_at = now

    def ensure_same_request(self, fingerprint: str) -> None:
        result = ReplayPaymentAbility.check(self.request_fingerprint, fingerprint)
        if not result.allowed:
            raise IdempotencyConflict(result.reason)

    def can_handle(self, attempt: int) -> bool:
        return ProcessPaymentAbility.check(
            self.completed_attempts, self.webhook_delivered_at is not None, attempt
        ).allowed

    def finish_attempt(self, attempt: int, now: datetime, error: str | None = None) -> None:
        ProcessPaymentAbility.check(
            self.completed_attempts, self.webhook_delivered_at is not None, attempt
        ).require()
        if error is None:
            DeliverWebhookAbility.check(self.status).require()
        self.completed_attempts = attempt
        self.last_error = error
        if error is None:
            self.webhook_delivered_at = now

    @property
    def needs_processing(self) -> bool:
        return self.status == PaymentStatus.PENDING

    @property
    def can_retry(self) -> bool:
        return RetryPaymentAbility.check(self.completed_attempts).allowed
