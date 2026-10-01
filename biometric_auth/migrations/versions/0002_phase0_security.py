"""Phase 0 security: timed lockout, token-free sessions, audit reason codes.

- users: failed_streak, lock_count, locked_until; timezone-aware created_at
- sessions: rebuilt. Raw tokens are no longer stored, only the access token's
  jti and a SHA-256 hash of the refresh token. Existing sessions are dropped:
  they were signed with the old public key and must not survive anyway.
- audit_logs: reason_code, indexes on user_id and timestamp, tz-aware timestamp

Revision ID: 0002_phase0_security
Revises: 0001_baseline
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_phase0_security"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("failed_streak", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lock_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("created_at", type_=sa.DateTime(timezone=True), existing_nullable=True)

    op.drop_table("sessions")
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_jti", sa.String(64), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_reason", sa.String(50), nullable=True),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_access_jti", "sessions", ["access_jti"], unique=True)

    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("reason_code", sa.String(50), nullable=True))
        batch.alter_column("timestamp", type_=sa.DateTime(timezone=True), existing_nullable=True)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("timestamp", type_=sa.DateTime(), existing_nullable=True)
        batch.drop_column("reason_code")

    op.drop_index("ix_sessions_access_jti", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_token", sa.String(500), nullable=False),
        sa.Column("refresh_token", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=True),
    )

    with op.batch_alter_table("users") as batch:
        batch.alter_column("created_at", type_=sa.DateTime(), existing_nullable=True)
        batch.drop_column("locked_until")
        batch.drop_column("lock_count")
        batch.drop_column("failed_streak")
