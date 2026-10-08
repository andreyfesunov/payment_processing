class DomainError(Exception):
    pass


class InvalidPayment(DomainError):
    pass


class OperationNotAllowed(DomainError):
    pass


class PaymentNotFound(DomainError):
    pass


class IdempotencyConflict(DomainError):
    pass
