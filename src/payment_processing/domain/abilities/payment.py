from dataclasses import dataclass
from decimal import Decimal

from payment_processing.domain.errors.payment import OperationNotAllowed
from payment_processing.domain.models.types import PaymentStatus


@dataclass(frozen=True, slots=True)
class AbilityResult:
    allowed: bool
    reason: str = ""

    def require(self) -> None:
        if not self.allowed:
            raise OperationNotAllowed(self.reason)


class CreatePaymentAbility:
    @staticmethod
    def check(amount: Decimal) -> AbilityResult:
        if not amount.is_finite() or amount <= 0 or amount >= Decimal("10000000000000000"):
            return AbilityResult(False, "Amount must be positive and fit NUMERIC(18,2)")
        if amount != amount.quantize(Decimal("0.01")):
            return AbilityResult(False, "Amount must have at most two decimal places")
        return AbilityResult(True)


class ReplayPaymentAbility:
    @staticmethod
    def check(original_fingerprint: str, request_fingerprint: str) -> AbilityResult:
        return AbilityResult(
            original_fingerprint == request_fingerprint,
            "Idempotency key was used with different payment details",
        )


class CompletePaymentAbility:
    @staticmethod
    def check(current: PaymentStatus, target: PaymentStatus) -> AbilityResult:
        if current != PaymentStatus.PENDING:
            return AbilityResult(False, "A completed payment cannot be processed again")
        if target == PaymentStatus.PENDING:
            return AbilityResult(False, "Processing must produce a terminal status")
        return AbilityResult(True)


class ProcessPaymentAbility:
    @staticmethod
    def check(completed_attempts: int, delivered: bool, attempt: int) -> AbilityResult:
        if delivered or attempt <= completed_attempts:
            return AbilityResult(False, "The message has already been handled")
        if not 1 <= attempt <= 3 or attempt != completed_attempts + 1:
            return AbilityResult(False, "Unexpected processing attempt")
        return AbilityResult(True)


class RetryPaymentAbility:
    @staticmethod
    def check(completed_attempts: int) -> AbilityResult:
        return AbilityResult(0 < completed_attempts < 3, "The processing attempt limit is reached")


class DeliverWebhookAbility:
    @staticmethod
    def check(status: PaymentStatus) -> AbilityResult:
        return AbilityResult(status != PaymentStatus.PENDING, "Payment has not been processed")
