set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

setup:
    python scripts/develop.py setup

run:
    python scripts/develop.py run

check:
    python scripts/develop.py check

test:
    python scripts/develop.py test

test-integration:
    python scripts/develop.py test-integration

migrate:
    python scripts/develop.py migrate

build:
    python scripts/develop.py build

logs:
    python scripts/develop.py logs

down:
    python scripts/develop.py down
