set windows-shell := ["powershell.exe", "-NoProfile", "-Command"]

setup:
    poetry sync
    poetry run pre-commit install --hook-type pre-commit --hook-type commit-msg
    poetry run python -c "from pathlib import Path; p = Path('.env'); p.exists() or p.write_bytes(Path('.env.example').read_bytes())"

run:
    docker compose build
    docker compose up -d --wait postgres rabbitmq
    docker compose run --rm --no-deps api alembic upgrade head
    docker compose up -d api consumer outbox

check:
    poetry check --lock
    poetry run pre-commit run --all-files

test:
    poetry run pytest -m "not integration"

test-integration:
    docker compose up -d --wait postgres rabbitmq
    poetry run pytest -m integration

migrate:
    poetry run alembic upgrade head

build:
    poetry build

logs:
    docker compose logs -f --tail 100

down:
    docker compose down
