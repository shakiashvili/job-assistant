import csv
import io
import json
import logging
import uuid
from typing import List, Optional, Dict
from sqlmodel import Session, select, or_, delete

from .database import engine, init_db
from .models import (
    JobPosting,
    ApplicationRecord,
    ApplicationTracker,
    ApplicationEvent,
    utc_now,
    ApplicationItem,
    ApplicationCreate,
    ApplicationUpdate,
    TrackerAnalyticsResponse,
)

logger = logging.getLogger(__name__)

UI_TO_DB_STATUS = {
    "Discovered": "DISCOVERED",
    "Saved": "SAVED",
    "Preparing": "PREPARING",
    "Ready to Apply": "READY_TO_APPLY",
    "Applied": "APPLIED",
    "Submitted": "APPLIED",
    "HR Screening": "HR_SCREEN",
    "Interviewing": "HR_SCREEN",
    "Technical Interview": "TECH_INTERVIEW",
    "Final Interview": "FINAL_INTERVIEW",
    "Offer": "OFFER",
    "Rejected": "REJECTED",
    "Withdrawn": "WITHDRAWN",
}

DB_TO_UI_STATUS = {
    "DISCOVERED": "Discovered",
    "STAGED": "Discovered",
    "SAVED": "Saved",
    "Saved": "Saved",
    "PREPARING": "Preparing",
    "READY_TO_APPLY": "Ready to Apply",
    "SUBMITTED": "Applied",
    "APPLIED": "Applied",
    "HR_SCREEN": "HR Screening",
    "INTERVIEW": "HR Screening",
    "TECH_INTERVIEW": "Technical Interview",
    "FINAL_INTERVIEW": "Final Interview",
    "OFFER": "Offer",
    "REJECTED": "Rejected",
    "WITHDRAWN": "Withdrawn",
}


class TrackerRepository:
    """
    Pure SQLModel repository replacing legacy tracker_store.py.
    Eliminates N+1 queries via single LEFT OUTER JOIN, enforces multi-user ownership,
    logs ApplicationEvent audit history, and provides pipeline analytics & CSV/JSON export.
    """

    def __init__(self):
        init_db()

    def _ownership_matches(
        self,
        row_user_id: Optional[int],
        user_id: Optional[int],
        is_guest: bool = False,
    ) -> bool:
        if user_id is None:
            return True
        if is_guest:
            return row_user_id is None or row_user_id == user_id
        return row_user_id == user_id

    def _record_to_item(
        self,
        rec: ApplicationRecord,
        job: Optional[JobPosting],
    ) -> ApplicationItem:
        ui_status = DB_TO_UI_STATUS.get(rec.submission_status, rec.submission_status or "Discovered")
        score = (
            int(round(job.suitability_score))
            if job and job.suitability_score is not None and job.suitability_score > 0
            else None
        )
        salary_str = None
        if job and job.salary_min and job.salary_max:
            salary_str = f"{int(job.salary_min):,}–{int(job.salary_max):,} {job.salary_currency or 'USD'}"
        interview_dt = rec.interview_date.strftime("%Y-%m-%d %H:%M") if rec.interview_date else None
        return ApplicationItem(
            id=f"app-{rec.id}",
            user_id=rec.user_id,
            company=job.company if job else "Hiring Company",
            role=job.title if job else "Specialist",
            portal=job.portal if job else "generic",
            url=job.url if job else "",
            status=ui_status,
            match_score=score,
            ats_score=score,
            recruiter_score=score,
            salary_estimate=salary_str,
            salary_expected=rec.submitted_salary,
            salary_offered=rec.salary_offered,
            interview_date=interview_dt,
            follow_up_date=rec.follow_up_date,
            recruiter_name=rec.recruiter_name,
            recruiter_email=rec.recruiter_email,
            company_reviews=None,
            cv_pdf_url=rec.custom_cv_path or rec.cv_pdf_path or None,
            cv_version_id=rec.cv_version_id,
            cover_letter_text=rec.cover_letter_text or rec.cover_letter or None,
            variant_used="tailored",
            applied_date=rec.applied_at.strftime("%Y-%m-%d") if rec.applied_at else None,
            outcome=rec.outcome,
            notes=rec.cover_letter_text or (job.match_rationale if job else ""),
        )

    def get_all(
        self,
        user_id: Optional[int] = None,
        is_guest: bool = False,
    ) -> List[ApplicationItem]:
        """Fetches all application records and associated JobPostings in a SINGLE SQL JOIN query."""
        with Session(engine) as session:
            stmt = (
                select(ApplicationRecord, JobPosting)
                .outerjoin(JobPosting, ApplicationRecord.job_posting_id == JobPosting.id)
            )
            if user_id is not None:
                if is_guest:
                    stmt = stmt.where(
                        or_(
                            ApplicationRecord.user_id == user_id,
                            ApplicationRecord.user_id.is_(None),
                        )
                    )
                else:
                    stmt = stmt.where(ApplicationRecord.user_id == user_id)

            stmt = stmt.order_by(ApplicationRecord.applied_at.desc())
            pairs = session.exec(stmt).all()
            return [self._record_to_item(rec, job) for rec, job in pairs]

    def get_by_id(
        self,
        item_id: str,
        user_id: Optional[int] = None,
        is_guest: bool = False,
    ) -> Optional[ApplicationItem]:
        rec_id_str = str(item_id).replace("app-", "")
        if not rec_id_str.isdigit():
            return None
        with Session(engine) as session:
            stmt = (
                select(ApplicationRecord, JobPosting)
                .outerjoin(JobPosting, ApplicationRecord.job_posting_id == JobPosting.id)
                .where(ApplicationRecord.id == int(rec_id_str))
            )
            pair = session.exec(stmt).first()
            if not pair:
                return None
            rec, job = pair
            if not self._ownership_matches(rec.user_id, user_id, is_guest=is_guest):
                raise PermissionError("Forbidden: application belongs to another user")
            return self._record_to_item(rec, job)

    def create(
        self,
        item_in: ApplicationCreate,
        user_id: Optional[int] = None,
    ) -> ApplicationItem:
        with Session(engine) as session:
            url = item_in.url or f"https://portal.local/{uuid.uuid4().hex[:8]}"
            job = session.exec(select(JobPosting).where(JobPosting.url == url)).first()
            if not job:
                job = JobPosting(
                    user_id=user_id,
                    portal=item_in.portal or "generic",
                    external_id=f"manual-{uuid.uuid4().hex[:8]}",
                    title=item_in.role,
                    company=item_in.company,
                    url=url,
                    market="INT_REMOTE",
                    is_remote=True,
                    language_requirements=["English"],
                    description_raw=item_in.notes or "",
                    suitability_score=float(item_in.match_score) if item_in.match_score is not None else 0.0,
                    match_score=float(item_in.match_score) if item_in.match_score is not None else 0.0,
                    match_rationale=item_in.notes or "Created from dashboard",
                    status="STAGED",
                )
                session.add(job)
                session.flush()

            db_status = UI_TO_DB_STATUS.get(item_in.status or "Saved", item_in.status or "STAGED")
            rec = ApplicationRecord(
                user_id=user_id,
                job_id=job.id,
                job_posting_id=job.id,
                cv_pdf_path=item_in.cv_pdf_url or "",
                custom_cv_path=item_in.cv_pdf_url or "",
                cv_version_id=item_in.cv_version_id,
                cover_letter=item_in.cover_letter_text or item_in.notes or "",
                cover_letter_text=item_in.notes or item_in.cover_letter_text or "",
                submitted_salary=item_in.salary_expected,
                salary_offered=item_in.salary_offered,
                recruiter_name=item_in.recruiter_name,
                recruiter_email=item_in.recruiter_email,
                follow_up_date=item_in.follow_up_date,
                outcome=item_in.outcome,
                submission_status=db_status,
                applied_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(rec)
            session.flush()

            if rec.id is not None:
                session.add(
                    ApplicationEvent(
                        application_id=rec.id,
                        user_id=user_id,
                        from_status=None,
                        to_status=db_status,
                        event_type="created",
                        note=f"Application created for {item_in.role} at {item_in.company}",
                    )
                )

            session.commit()
            session.refresh(rec)
            return self._record_to_item(rec, job)

    def update(
        self,
        item_id: str,
        item_update: ApplicationUpdate,
        user_id: Optional[int] = None,
        is_guest: bool = False,
    ) -> Optional[ApplicationItem]:
        rec_id_str = str(item_id).replace("app-", "")
        if not rec_id_str.isdigit():
            return None
        with Session(engine) as session:
            rec = session.get(ApplicationRecord, int(rec_id_str))
            if not rec:
                return None
            if not self._ownership_matches(rec.user_id, user_id, is_guest=is_guest):
                raise PermissionError("Forbidden: application belongs to another user")

            job = session.get(JobPosting, rec.job_posting_id) if rec.job_posting_id else None
            old_status = rec.submission_status

            if item_update.status is not None:
                rec.submission_status = UI_TO_DB_STATUS.get(item_update.status, item_update.status)
                if job:
                    job.status = (
                        "APPLIED"
                        if rec.submission_status in ("SUBMITTED", "APPLIED")
                        else ("REJECTED" if rec.submission_status == "REJECTED" else job.status)
                    )
                    session.add(job)
            if item_update.notes is not None:
                rec.cover_letter_text = item_update.notes
            if item_update.cover_letter_text is not None:
                rec.cover_letter_text = item_update.cover_letter_text
                rec.cover_letter = item_update.cover_letter_text
            if item_update.cv_pdf_url is not None:
                rec.custom_cv_path = item_update.cv_pdf_url
                rec.cv_pdf_path = item_update.cv_pdf_url
            if item_update.cv_version_id is not None:
                rec.cv_version_id = item_update.cv_version_id
            if item_update.salary_expected is not None:
                rec.submitted_salary = item_update.salary_expected
            if item_update.salary_offered is not None:
                rec.salary_offered = item_update.salary_offered
            if item_update.recruiter_name is not None:
                rec.recruiter_name = item_update.recruiter_name
            if item_update.recruiter_email is not None:
                rec.recruiter_email = item_update.recruiter_email
            if item_update.follow_up_date is not None:
                rec.follow_up_date = item_update.follow_up_date
            if item_update.outcome is not None:
                rec.outcome = item_update.outcome

            if job:
                if item_update.company is not None:
                    job.company = item_update.company
                if item_update.role is not None:
                    job.title = item_update.role
                if item_update.match_score is not None:
                    job.suitability_score = float(item_update.match_score)
                session.add(job)

            rec.updated_at = utc_now()
            session.add(rec)

            if item_update.status is not None and rec.submission_status != old_status and rec.id is not None:
                session.add(
                    ApplicationEvent(
                        application_id=rec.id,
                        user_id=rec.user_id,
                        from_status=old_status,
                        to_status=rec.submission_status,
                        event_type="status_change",
                        note=f"Status changed from {old_status} to {rec.submission_status}",
                    )
                )

            session.commit()
            session.refresh(rec)
            return self._record_to_item(rec, job)

    def delete(
        self,
        item_id: str,
        user_id: Optional[int] = None,
        is_guest: bool = False,
    ) -> bool:
        rec_id_str = str(item_id).replace("app-", "")
        if not rec_id_str.isdigit():
            return False
        with Session(engine) as session:
            rec = session.get(ApplicationRecord, int(rec_id_str))
            if not rec:
                return False
            if not self._ownership_matches(rec.user_id, user_id, is_guest=is_guest):
                raise PermissionError("Forbidden: application belongs to another user")
            session.exec(
                delete(ApplicationEvent).where(ApplicationEvent.application_id == rec.id)
            )
            session.delete(rec)
            session.commit()
            return True

    def get_analytics(
        self,
        user_id: Optional[int] = None,
        is_guest: bool = False,
    ) -> TrackerAnalyticsResponse:
        items = self.get_all(user_id=user_id, is_guest=is_guest)
        total = len(items)
        by_status: Dict[str, int] = {}
        by_portal: Dict[str, Dict[str, int]] = {}
        by_role: Dict[str, Dict[str, int]] = {}

        submitted_statuses = {
            "Applied",
            "HR Screening",
            "Technical Interview",
            "Final Interview",
            "Offer",
            "Rejected",
        }
        interview_statuses = {
            "HR Screening",
            "Technical Interview",
            "Final Interview",
            "Offer",
        }

        submitted = 0
        awaiting = 0
        interviews = 0
        offers = 0
        rejections = 0
        withdrawn = 0

        for it in items:
            st = it.status or "Discovered"
            by_status[st] = by_status.get(st, 0) + 1
            pt = it.portal or "generic"
            p_bucket = by_portal.setdefault(pt, {"total": 0, "applied": 0, "interviews": 0, "offers": 0})
            p_bucket["total"] += 1

            rl = it.role or "Specialist"
            r_bucket = by_role.setdefault(rl, {"total": 0, "applied": 0, "interviews": 0, "offers": 0})
            r_bucket["total"] += 1

            if st in submitted_statuses:
                submitted += 1
                p_bucket["applied"] += 1
                r_bucket["applied"] += 1
            if st == "Applied":
                awaiting += 1
            if st in interview_statuses:
                interviews += 1
                p_bucket["interviews"] += 1
                r_bucket["interviews"] += 1
            if st == "Offer":
                offers += 1
                p_bucket["offers"] += 1
                r_bucket["offers"] += 1
            if st == "Rejected":
                rejections += 1
            if st == "Withdrawn":
                withdrawn += 1

        denom = max(submitted, total, 1)
        responded = interviews + rejections
        response_rate = round((responded / denom) * 100.0, 1) if total > 0 else 0.0
        interview_rate = round((interviews / denom) * 100.0, 1) if total > 0 else 0.0
        offer_rate = round((offers / denom) * 100.0, 1) if total > 0 else 0.0

        return TrackerAnalyticsResponse(
            total_tracked=total,
            applications_submitted=submitted,
            awaiting_response=awaiting,
            interviews_received=interviews,
            offers_received=offers,
            rejections=rejections,
            withdrawn=withdrawn,
            response_rate_pct=response_rate,
            interview_conversion_rate_pct=interview_rate,
            offer_rate_pct=offer_rate,
            by_status=by_status,
            by_portal=by_portal,
            by_role=by_role,
        )

    def export_applications(
        self,
        user_id: Optional[int] = None,
        is_guest: bool = False,
        fmt: str = "json",
    ) -> str:
        items = self.get_all(user_id=user_id, is_guest=is_guest)
        dicts = [item.model_dump() for item in items]
        if fmt.lower() == "csv":
            output = io.StringIO()
            fieldnames = [
                "id",
                "company",
                "role",
                "status",
                "portal",
                "match_score",
                "ats_score",
                "applied_date",
                "recruiter_name",
                "recruiter_email",
                "follow_up_date",
                "salary_expected",
                "salary_offered",
                "outcome",
                "url",
                "notes",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in dicts:
                writer.writerow(row)
            return output.getvalue()
        return json.dumps(dicts, indent=2, ensure_ascii=False)


tracker_repository = TrackerRepository()
tracker_store = tracker_repository
