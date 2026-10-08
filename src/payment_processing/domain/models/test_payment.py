from datetime import UTC, datetime
from decimal import Decimal

import pytest

from payment_processing.domain.errors.payment import (
    IdempotencyConflict,
    InvalidPayment,
    OperationNotAllowed,
)
from payment_processing.domain.models.payment import Payment, PaymentDetails
from payment_processing.domain.models.types import Currency, PaymentStatus

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def details(amount: str = "10.50") -> PaymentDetails:
    return PaymentDetails(Decimal(amount), Currency.RUB, "Order", {}, "https://example.com/hook")


def test_creation_emits_one_event_and_keeps_decimal() -> None:
    payment = Payment.create(details(), "key", NOW)
    assert payment.status == PaymentStatus.PENDING
    assert payment.details.amount == Decimal("10.50")
    assert payment.processed_at is None
    assert len(payment.events) == 1
    assert payment.events[0].payment_id == payment.id
    assert payment.events[0].attempt == 1


@pytest.mark.parametrize("amount", ["0", "-1", "0.001", "1e16", "NaN", "Infinity"])
def test_invalid_amount_is_rejected(amount: str) -> None:
    with pytest.raises(InvalidPayment):
        Payment.create(details(amount), "key", NOW)


@pytest.mark.parametrize("amount", ["0.01", "9999999999999999.99", "10.500"])
def test_valid_amount_boundaries(amount: str) -> None:
    assert Payment.create(details(amount), "key", NOW).details.amount == Decimal(amount)


@pytest.mark.parametrize("status", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED])
def test_terminal_status_cannot_change(status: PaymentStatus) -> None:
    payment = Payment.create(details(), "key", NOW)
    payment.complete(status, NOW)
    assert payment.processed_at == NOW
    with pytest.raises(OperationNotAllowed):
        payment.complete(PaymentStatus.FAILED, NOW)
    assert payment.status == status


def test_pending_is_not_a_processing_result() -> None:
    payment = Payment.create(details(), "key", NOW)
    with pytest.raises(OperationNotAllowed):
        payment.complete(PaymentStatus.PENDING, NOW)


def test_fingerprint_normalizes_money_and_object_key_order() -> None:
    left = PaymentDetails(Decimal("10.5"), Currency.RUB, "Order", {"a": 1, "b": 2}, "url")
    right = PaymentDetails(Decimal("10.50"), Currency.RUB, "Order", {"b": 2, "a": 1}, "url")
    assert left.fingerprint() == right.fingerprint()
    assert left.fingerprint() != details("11").fingerprint()


def test_retry_progress_and_delivery_are_independent_of_payment_status() -> None:
    payment = Payment.create(details(), "key", NOW)
    payment.complete(PaymentStatus.SUCCEEDED, NOW)
    payment.finish_attempt(1, NOW, "Timeout")
    assert not payment.can_handle(1)
    assert not payment.can_handle(3)
    assert payment.can_handle(2)
    assert payment.webhook_delivered_at is None
    payment.finish_attempt(2, NOW)
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.webhook_delivered_at == NOW
    assert payment.last_error is None
    assert not payment.can_handle(3)


def test_retry_event_has_new_identity_and_same_payment() -> None:
    event = Payment.create(details(), "key", NOW).events[0]
    retry = event.retry(NOW, "Timeout")
    assert retry.event_id != event.event_id
    assert retry.payment_id == event.payment_id
    assert retry.attempt == 2
    assert retry.error == "Timeout"


@pytest.mark.parametrize("key", ["", "   ", "x" * 256])
def test_invalid_key_is_rejected(key: str) -> None:
    with pytest.raises(InvalidPayment):
        Payment.create(details(), key, NOW)


def test_pending_payment_cannot_be_marked_notified() -> None:
    payment = Payment.create(details(), "key", NOW)
    with pytest.raises(OperationNotAllowed):
        payment.finish_attempt(1, NOW)
    assert payment.completed_attempts == 0
    assert payment.webhook_delivered_at is None


def test_third_failure_exhausts_retry_ability() -> None:
    payment = Payment.create(details(), "key", NOW)
    for attempt in range(1, 4):
        payment.finish_attempt(attempt, NOW, "Unavailable")
        assert payment.can_retry is (attempt < 3)
    assert not payment.can_handle(4)


@pytest.mark.parametrize("description", ["", "x" * 1001])
def test_invalid_description_is_rejected(description: str) -> None:
    invalid = PaymentDetails(Decimal("1"), Currency.RUB, description, {}, "https://example.com")
    with pytest.raises(InvalidPayment):
        Payment.create(invalid, "key", NOW)


def test_idempotency_replay_requires_identical_details() -> None:
    payment = Payment.create(details(), "key", NOW)
    payment.ensure_same_request(details("10.500").fingerprint())
    with pytest.raises(IdempotencyConflict):
        payment.ensure_same_request(details("11").fingerprint())
