from enum import StrEnum

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
