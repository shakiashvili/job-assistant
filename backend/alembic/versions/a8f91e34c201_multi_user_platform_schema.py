"""multi_user_platform_schema

Revision ID: a8f91e34c201
Revises: 75cd228268f5
Create Date: 2026-11-14 14:35:00.000000

"""
from typing import Sequence, Union
import json
from alembic import op
import sqlalchemy as sa


revision: str = "a8f91e34c201"
down_revision: Union[str, Sequence[str], None] = "75cd228268f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, col_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(c["name"] == col_name for c in inspector.get_columns(table_name))


def _add_column_if_missing(inspector: sa.Inspector, table: str, col: sa.Column) -> None:
    if not _has_column(inspector, table, col.name):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(col)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Extend existing tables safely
    _add_column_if_missing(inspector, "candidate_profiles", sa.Column("user_id", sa.Integer(), nullable=True))

    for col in [
        sa.Column("remote_type", sa.String(), nullable=False, server_default="REMOTE"),
        sa.Column("employment_type", sa.String(), nullable=False, server_default="FULL_TIME"),
        sa.Column("experience_min_years", sa.Float(), nullable=True),
        sa.Column("seniority_level", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("posting_date", sa.String(), nullable=True),
        sa.Column("is_expired", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    ]:
        _add_column_if_missing(inspector, "job_postings", col)

    for col in [
        sa.Column("job_posting_id", sa.Integer(), nullable=True),
        sa.Column("salary_expected", sa.String(), nullable=True),
        sa.Column("recruiter_name", sa.String(), nullable=True),
        sa.Column("recruiter_email", sa.String(), nullable=True),
        sa.Column("follow_up_date", sa.String(), nullable=True),
        sa.Column("cv_version_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
    ]:
        _add_column_if_missing(inspector, "application_tracker", col)

    for col in [
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("cv_version_id", sa.Integer(), nullable=True),
        sa.Column("salary_offered", sa.String(), nullable=True),
        sa.Column("recruiter_name", sa.String(), nullable=True),
        sa.Column("recruiter_email", sa.String(), nullable=True),
        sa.Column("follow_up_date", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
    ]:
        _add_column_if_missing(inspector, "application_records", col)

    for col in [
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("technical_glossary", sa.JSON(), nullable=True),
        sa.Column("follow_up_questions", sa.JSON(), nullable=True),
        sa.Column("reflection_notes", sa.Text(), nullable=True),
    ]:
        _add_column_if_missing(inspector, "interview_rounds", col)

    # 2. Create new multi-user relational tables if not already present
    if not _has_table(inspector, "candidate_skills"):
        op.create_table(
            "candidate_skills",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("profile_id", sa.Integer(), nullable=True),
            sa.Column("skill_name", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("proficiency", sa.String(), nullable=True),
            sa.Column("years_used", sa.Float(), nullable=True),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_candidate_skills_user_cat", "candidate_skills", ["user_id", "category"], unique=False)

    if not _has_table(inspector, "candidate_experiences"):
        op.create_table(
            "candidate_experiences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("profile_id", sa.Integer(), nullable=True),
            sa.Column("company", sa.String(), nullable=False),
            sa.Column("role_title", sa.String(), nullable=False),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("start_date", sa.String(), nullable=True),
            sa.Column("end_date", sa.String(), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False),
            sa.Column("highlights", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table(inspector, "candidate_educations"):
        op.create_table(
            "candidate_educations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("profile_id", sa.Integer(), nullable=True),
            sa.Column("institution", sa.String(), nullable=False),
            sa.Column("degree", sa.String(), nullable=False),
            sa.Column("field_of_study", sa.String(), nullable=True),
            sa.Column("graduation_year", sa.String(), nullable=True),
            sa.Column("coursework", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["profile_id"], ["candidate_profiles.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table(inspector, "candidate_documents"):
        op.create_table(
            "candidate_documents",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("job_posting_id", sa.Integer(), nullable=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("storage_path", sa.String(), nullable=False),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("cv_style", sa.String(), nullable=False),
            sa.Column("cv_language", sa.String(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256_hash", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_candidate_documents_user_type", "candidate_documents", ["user_id", "doc_type"], unique=False)
        op.create_index("ix_candidate_documents_filename", "candidate_documents", ["filename"], unique=False)

    if not _has_table(inspector, "user_job_matches"):
        op.create_table(
            "user_job_matches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("job_posting_id", sa.Integer(), nullable=False),
            sa.Column("suitability_score", sa.Float(), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=False),
            sa.Column("match_tier", sa.String(), nullable=False),
            sa.Column("adjacent_role_tag", sa.String(), nullable=True),
            sa.Column("skill_overlap_pct", sa.Integer(), nullable=True),
            sa.Column("matched_skills", sa.JSON(), nullable=False),
            sa.Column("missing_skills", sa.JSON(), nullable=False),
            sa.Column("match_breakdown", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("filter_out_reason", sa.String(), nullable=True),
            sa.Column("match_rationale", sa.Text(), nullable=False),
            sa.Column("is_saved", sa.Boolean(), nullable=False),
            sa.Column("is_ignored", sa.Boolean(), nullable=False),
            sa.Column("is_new", sa.Boolean(), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "job_posting_id", name="uq_user_job_match"),
        )
        op.create_index(
            "ix_user_job_matches_user_status_score",
            "user_job_matches",
            ["user_id", "status", "suitability_score"],
            unique=False,
        )

    if not _has_table(inspector, "saved_jobs"):
        op.create_table(
            "saved_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("job_posting_id", sa.Integer(), nullable=False),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "job_posting_id", name="uq_user_saved_job"),
        )

    if not _has_table(inspector, "application_events"):
        op.create_table(
            "application_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("from_status", sa.String(), nullable=True),
            sa.Column("to_status", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_application_events_application_id", "application_events", ["application_id"], unique=False)

    if not _has_table(inspector, "interview_notes"):
        op.create_table(
            "interview_notes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("interview_round_id", sa.Integer(), nullable=True),
            sa.Column("application_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("note_type", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["interview_round_id"], ["interview_rounds.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table(inspector, "saved_searches"):
        op.create_table(
            "saved_searches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("filters", sa.JSON(), nullable=False),
            sa.Column("notify_on_new", sa.Boolean(), nullable=False),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table(inspector, "notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("job_posting_id", sa.Integer(), nullable=True),
            sa.Column("saved_search_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("notification_type", sa.String(), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"]),
            sa.ForeignKeyConstraint(["saved_search_id"], ["saved_searches.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_notifications_user_read_created",
            "notifications",
            ["user_id", "is_read", "created_at"],
            unique=False,
        )

    if not _has_table(inspector, "scrape_tasks"):
        op.create_table(
            "scrape_tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("portals", sa.JSON(), nullable=False),
            sa.Column("progress_pct", sa.Integer(), nullable=False),
            sa.Column("current_portal", sa.String(), nullable=True),
            sa.Column("result_summary", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id"),
        )

    # 3. Deterministic ownership backfill ONLY when owner_email is explicitly verified
    try:
        from app.services.crypto_service import blind_index, decrypt_str

        users_rows = bind.execute(sa.text("SELECT id, email_hash FROM users")).fetchall()
        hash_to_uid = {row[1]: row[0] for row in users_rows if row[1]}

        prof_rows = bind.execute(
            sa.text("SELECT id, user_id, parsed_skills FROM candidate_profiles WHERE user_id IS NULL")
        ).fetchall()
        for pid, uid, raw_ps in prof_rows:
            if uid is not None or not raw_ps:
                continue
            dec = decrypt_str(str(raw_ps))
            if not dec:
                continue
            try:
                ps_obj = json.loads(dec)
            except Exception:
                continue
            owner_em = str((ps_obj or {}).get("owner_email") or "").strip().lower()
            if owner_em and owner_em != "guest@talentflow.local":
                matched_uid = hash_to_uid.get(blind_index(owner_em))
                if matched_uid:
                    bind.execute(
                        sa.text("UPDATE candidate_profiles SET user_id = :uid WHERE id = :pid"),
                        {"uid": matched_uid, "pid": pid},
                    )
    except Exception:
        # Never fail schema upgrade if optional backfill encounters legacy unencrypted test rows
        pass


def downgrade() -> None:
    for tbl in [
        "scrape_tasks",
        "notifications",
        "saved_searches",
        "interview_notes",
        "application_events",
        "saved_jobs",
        "user_job_matches",
        "candidate_documents",
        "candidate_educations",
        "candidate_experiences",
        "candidate_skills",
    ]:
        op.drop_table(tbl)
