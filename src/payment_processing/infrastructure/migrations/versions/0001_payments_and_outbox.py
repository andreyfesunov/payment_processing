from alembic import op
from sqlalchemy import UUID, CheckConstraint, Column, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        Column("id", UUID, primary_key=True),
        Column("amount", Numeric(18, 2), nullable=False),
        Column("currency", String(3), nullable=False),
        Column("description", String(1000), nullable=False),
        Column("metadata", JSONB, nullable=False),
        Column("status", String(16), nullable=False),
        Column("idempotency_key", String(255), nullable=False, unique=True),
        Column("request_fingerprint", String(64), nullable=False),
        Column("webhook_url", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("processed_at", DateTime(timezone=True)),
        Column("webhook_delivered_at", DateTime(timezone=True)),
        Column("completed_attempts", Integer, nullable=False),
        Column("last_error", Text),
        CheckConstraint("amount > 0", name="payment_positive_amount"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="payment_currency"),
        CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="payment_status"),
        CheckConstraint("completed_attempts BETWEEN 0 AND 3", name="payment_attempts"),
        CheckConstraint(
            "(status = 'pending' AND processed_at IS NULL) OR "
            "(status != 'pending' AND processed_at IS NOT NULL)",
            name="payment_processing_date",
        ),
        CheckConstraint(
            "webhook_delivered_at IS NULL OR status != 'pending'", name="payment_webhook_date"
        ),
    )
    op.create_table(
        "outbox",
        Column("id", UUID, primary_key=True),
        Column("event_type", String(100), nullable=False),
        Column("payload", JSONB, nullable=False),
        Column("route", String(100), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("published_at", DateTime(timezone=True)),
        Column("publish_attempts", Integer, nullable=False),
        Column("last_error", Text),
    )
    op.create_index(
        "outbox_pending_idx",
        "outbox",
        ["available_at", "created_at"],
        postgresql_where=text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("payments")
