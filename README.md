# Payment processing

An asynchronous payment processing service built with FastAPI, PostgreSQL and RabbitMQ.

## Local infrastructure

Requirements: Docker Engine with Docker Compose.

```console
docker compose up -d --wait
```

PostgreSQL is available on `localhost:5432`. RabbitMQ uses `localhost:5672`;
its management UI is at <http://localhost:15672>. Default development credentials
are `payments` / `payments`. Copy `.env.example` to `.env` to override settings.

```console
docker compose down
```

Stopping the environment preserves database and broker volumes.
