FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir poetry==2.3.2
COPY pyproject.toml poetry.lock VERSION ./
RUN poetry sync --only main --no-root
COPY src ./src
COPY alembic.ini ./
RUN poetry sync --only main && useradd --create-home app && chown -R app:app /app
USER app
CMD ["python", "-m", "payment_processing.main", "api"]
