"""durable_storage_and_scrape_recovery

Revision ID: f2b8c45d0e32
Revises: e1a7f34b9c21
Create Date: 2026-11-20 11:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "f2b8c45d0e32"
down_revision: Union[str, Sequence[str], None] = "e1a7f34b9c21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "candidate_documents"):
        if not _has_column(inspector, "candidate_documents", "storage_backend"):
            op.add_column(
                "candidate_documents",
                sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default=sa.text("'local'")),
            )
        if not _has_column(inspector, "candidate_documents", "object_key"):
            op.add_column(
                "candidate_documents",
                sa.Column("object_key", sa.String(length=512), nullable=True),
            )
        if not _has_column(inspector, "candidate_documents", "encrypted_content"):
            op.add_column(
                "candidate_documents",
                sa.Column("encrypted_content", sa.Text(), nullable=True),
            )

    if _has_table(inspector, "scrape_tasks"):
        if not _has_column(inspector, "scrape_tasks", "allow_network"):
            op.add_column(
                "scrape_tasks",
                sa.Column("allow_network", sa.Boolean(), nullable=False, server_default=sa.true()),
            )
        if not _has_column(inspector, "scrape_tasks", "worker_id"):
            op.add_column(
                "scrape_tasks",
                sa.Column("worker_id", sa.String(length=128), nullable=True),
            )
        if not _has_column(inspector, "scrape_tasks", "started_at"):
            op.add_column(
                "scrape_tasks",
                sa.Column("started_at", sa.DateTime(), nullable=True),
            )
        if not _has_column(inspector, "scrape_tasks", "heartbeat_at"):
            op.add_column(
                "scrape_tasks",
                sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            )
        if not _has_index(inspector, "scrape_tasks", "ix_scrape_tasks_heartbeat_at"):
            op.create_index("ix_scrape_tasks_heartbeat_at", "scrape_tasks", ["heartbeat_at"])
        if not _has_column(inspector, "scrape_tasks", "attempt_count"):
            op.add_column(
                "scrape_tasks",
                sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
        if not _has_column(inspector, "scrape_tasks", "max_attempts"):
            op.add_column(
                "scrape_tasks",
                sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("2")),
            )
        if not _has_column(inspector, "scrape_tasks", "timeout_seconds"):
            op.add_column(
                "scrape_tasks",
                sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("180")),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "scrape_tasks"):
        if _has_index(inspector, "scrape_tasks", "ix_scrape_tasks_heartbeat_at"):
            op.drop_index("ix_scrape_tasks_heartbeat_at", table_name="scrape_tasks")
        for col in ("timeout_seconds", "max_attempts", "attempt_count", "heartbeat_at", "started_at", "worker_id", "allow_network"):
            if _has_column(inspector, "scrape_tasks", col):
                op.drop_column("scrape_tasks", col)

    if _has_table(inspector, "candidate_documents"):
        for col in ("encrypted_content", "object_key", "storage_backend"):
            if _has_column(inspector, "candidate_documents", col):
                op.drop_column("candidate_documents", col)
