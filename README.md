# Payment processing

An asynchronous service that processes payments and notifies clients via webhooks.

Requires Python 3.12, Poetry, just, and Docker Compose.

```sh
just setup
just run
```

API: `http://localhost:8000`. Use `X-API-Key` with `API_KEY` from `.env`.

Stop: `just down`.
