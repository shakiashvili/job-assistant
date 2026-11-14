"""ai_observability_cv_versions

Revision ID: b9f4e21a8d10
Revises: a8f91e34c201
Create Date: 2026-11-14 19:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "b9f4e21a8d10"
down_revision: Union[str, Sequence[str], None] = "a8f91e34c201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "cv_versions"):
        op.create_table(
            "cv_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("job_posting_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("target_role", sa.String(), nullable=False),
            sa.Column("target_company", sa.String(), nullable=False),
            sa.Column("edition", sa.String(), nullable=False),
            sa.Column("cv_language", sa.String(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("structured_content", sa.Text(), nullable=False),
            sa.Column("rendered_html", sa.Text(), nullable=False),
            sa.Column("cover_letter", sa.Text(), nullable=False),
            sa.Column("motivational_letter", sa.Text(), nullable=False),
            sa.Column("pdf_filename", sa.String(), nullable=True),
            sa.Column("docx_filename", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_cv_versions_user_created", "cv_versions", ["user_id", "created_at"])

    if not _has_table(inspector, "ai_operation_logs"):
        op.create_table(
            "ai_operation_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("operation_type", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("prompt_hash", sa.String(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
            sa.Column("cache_hit", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("error_category", sa.String(), nullable=True),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("schema_valid", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ai_ops_user_created", "ai_operation_logs", ["user_id", "created_at"])
        op.create_index("ix_ai_ops_type_status", "ai_operation_logs", ["operation_type", "status"])

    if not _has_table(inspector, "ai_cache_entries"):
        op.create_table(
            "ai_cache_entries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("cache_key", sa.String(), nullable=False),
            sa.Column("operation_type", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("response_payload", sa.JSON(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cache_key"),
        )
        op.create_index("ix_ai_cache_entries_cache_key", "ai_cache_entries", ["cache_key"])


def downgrade() -> None:
    op.drop_table("ai_cache_entries")
    op.drop_table("ai_operation_logs")
    op.drop_table("cv_versions")
