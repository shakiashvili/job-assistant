"""nullable_applied_at_and_experience_years

Revision ID: c4e8a12f9b30
Revises: b9f4e21a8d10
Create Date: 2026-11-18 20:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a12f9b30"
down_revision: Union[str, Sequence[str], None] = "b9f4e21a8d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, "candidate_profiles", "experience_years"):
        with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
            batch_op.alter_column(
                "experience_years",
                existing_type=sa.Float(),
                nullable=True,
            )

    if _column_exists(inspector, "application_records", "applied_at"):
        with op.batch_alter_table("application_records", schema=None) as batch_op:
            batch_op.alter_column(
                "applied_at",
                existing_type=sa.DateTime(),
                nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, "application_records", "applied_at"):
        with op.batch_alter_table("application_records", schema=None) as batch_op:
            batch_op.alter_column(
                "applied_at",
                existing_type=sa.DateTime(),
                nullable=False,
            )

    if _column_exists(inspector, "candidate_profiles", "experience_years"):
        with op.batch_alter_table("candidate_profiles", schema=None) as batch_op:
            batch_op.alter_column(
                "experience_years",
                existing_type=sa.Float(),
                nullable=False,
            )
