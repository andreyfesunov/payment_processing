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

## Development

Use Python 3.12, Poetry 2, Node.js 22 and Docker Compose.

```console
poetry env use 3.12
poetry sync
npm ci
poetry run pre-commit install
poetry run pre-commit run --all-files
```

The hooks run Ruff and strict mypy, and validate commit messages with commitlint.
Use Conventional Commits, for example `feat: add payment creation`.
