import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader

from payment_processing.application.usecases.create_payment import CreatePayment
from payment_processing.application.usecases.get_payment import GetPayment
from payment_processing.domain.errors.payment import (
    DomainError,
    IdempotencyConflict,
    InvalidPayment,
    OperationNotAllowed,
    PaymentNotFound,
)
from payment_processing.presentation.http.handlers.payments import payment_router


def create_http_app(
    create_payment: CreatePayment,
    get_payment: GetPayment,
    api_key: str,
    version: str,
    check_database: Callable[[], Awaitable[None]],
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Payment processing",
        version=version,
        lifespan=lifespan,
        dependencies=[Depends(APIKeyHeader(name="X-API-Key", auto_error=False))],
    )

    @app.middleware("http")
    async def authenticate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        provided = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(provided.encode(), api_key.encode()):
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)
        return await call_next(request)

    async def domain_error(request: Request, error: Exception) -> JSONResponse:
        statuses: dict[type[Exception], int] = {
            PaymentNotFound: 404,
            IdempotencyConflict: 409,
            InvalidPayment: 422,
            OperationNotAllowed: 409,
        }
        status = statuses.get(type(error), 400)
        return JSONResponse({"detail": str(error)}, status_code=status)

    app.add_exception_handler(DomainError, domain_error)
    app.include_router(payment_router(create_payment, get_payment))

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        await check_database()
        return {"status": "ok", "version": version}

    return app
