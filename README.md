# Payment processing

An asynchronous payment processing service built with FastAPI, PostgreSQL and RabbitMQ.

Requirements: Python 3.12, Poetry 2, Node.js 22, Just and Docker Compose.

```console
poetry env use 3.12
just setup
```

Settings are in `.env`, created from `.env.example` without overwriting existing values.

```console
just check
just test
just test-integration
just build
just down
```

Checks use Ruff, strict mypy and commitlint. Use Conventional Commits.
`VERSION` supplies the API and package version. `just down` preserves volumes.
