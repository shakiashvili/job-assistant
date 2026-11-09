import json
import logging
import uuid
from typing import List, Optional
from sqlmodel import Session, select
from ..config import APPLICATIONS_FILE
from ..database import engine, init_db
from ..models.db_models import JobPosting, ApplicationRecord, utc_now
from ..models.schemas import ApplicationItem, ApplicationCreate, ApplicationUpdate

logger = logging.getLogger(__name__)

# Map between UI status names and ApplicationRecord.submission_status
UI_TO_DB_STATUS = {
    "Discovered": "DISCOVERED",
    "Saved": "DISCOVERED",
    "Applied": "APPLIED",
    "HR Screening": "HR_SCREEN",
    "Interviewing": "HR_SCREEN",
    "Technical Interview": "TECH_INTERVIEW",
    "Offer": "OFFER",
    "Rejected": "REJECTED",
}
DB_TO_UI_STATUS = {
    "DISCOVERED": "Discovered",
    "STAGED": "Discovered",
    "Saved": "Discovered",
    "SUBMITTED": "Applied",
    "APPLIED": "Applied",
    "HR_SCREEN": "HR Screening",
    "INTERVIEW": "HR Screening",
    "TECH_INTERVIEW": "Technical Interview",
    "OFFER": "Offer",
    "REJECTED": "Rejected",
}


class TrackerStore:
    """
    Relational Database-backed Application Tracker store (SQLModel / SQLAlchemy).
    Persists all applications in `application_records` and `job_postings` tables.
    """

    def __init__(self, filepath=APPLICATIONS_FILE):
        self.filepath = filepath
        init_db()
        self._seed_from_json_if_empty()

    def _seed_from_json_if_empty(self) -> None:
        with Session(engine) as session:
            existing_app = session.exec(select(ApplicationRecord)).first()
            if existing_app:
                return
            if not self.filepath.exists():
                return
            try:
                raw = json.loads(self.filepath.read_text(encoding="utf-8"))
                for entry in raw:
                    url = entry.get("url") or f"https://portal.local/{uuid.uuid4().hex[:6]}"
                    portal = entry.get("portal") or "generic"
                    ext_id = entry.get("id") or f"seed-{uuid.uuid4().hex[:6]}"

                    job = session.exec(select(JobPosting).where(JobPosting.url == url)).first()
                    if not job:
                        job = JobPosting(
                            portal=portal,
                            external_id=ext_id,
                            title=entry.get("role", "QA Engineer"),
                            company=entry.get("company", "Company"),
                            url=url,
                            market="INT_REMOTE",
                            is_remote=True,
                            language_requirements=["English"],
                            description_raw=entry.get("notes") or "",
                            suitability_score=float(entry.get("match_score") or 85.0),
                            match_rationale=entry.get("notes") or "Seeded from tracker",
                            status="STAGED",
                        )
                        session.add(job)
                        session.commit()
                        session.refresh(job)

                    db_status = UI_TO_DB_STATUS.get(entry.get("status", "Saved"), "STAGED")
                    rec = ApplicationRecord(
                        job_posting_id=job.id,
                        custom_cv_path=entry.get("cv_pdf_url") or "/api/resumes/resume_qa_automation.pdf",
                        cover_letter_text=entry.get("notes") or "",
                        submission_status=db_status,
                        applied_at=utc_now(),
                    )
                    session.add(rec)
                session.commit()
            except Exception as e:
                logger.warning(f"Tracker seed migration note: {e}")

    def _record_to_item(self, rec: ApplicationRecord, job: Optional[JobPosting]) -> ApplicationItem:
        ui_status = DB_TO_UI_STATUS.get(rec.submission_status, "Discovered")
        score = int(round(job.suitability_score)) if job and job.suitability_score else 85
        salary_str = None
        if job and job.salary_min and job.salary_max:
            salary_str = f"{int(job.salary_min):,}–{int(job.salary_max):,} {job.salary_currency or 'USD'}"
        interview_dt = rec.interview_date.strftime("%Y-%m-%d %H:%M") if rec.interview_date else None
        return ApplicationItem(
            id=f"app-{rec.id}",
            company=job.company if job else "Hiring Company",
            role=job.title if job else "Specialist",
            portal=job.portal if job else "generic",
            url=job.url if job else "",
            status=ui_status,
            match_score=score,
            ats_score=score,
            recruiter_score=min(100, score + 3),
            salary_estimate=salary_str,
            interview_date=interview_dt,
            company_reviews=25,
            cv_pdf_url=rec.custom_cv_path or None,
            variant_used="qa_automation",
            applied_date=rec.applied_at.strftime("%Y-%m-%d") if rec.applied_at else None,
            notes=rec.cover_letter_text or (job.match_rationale if job else ""),
        )

    def get_all(self) -> List[ApplicationItem]:
        with Session(engine) as session:
            records = session.exec(
                select(ApplicationRecord).order_by(ApplicationRecord.applied_at.desc())
            ).all()
            items: List[ApplicationItem] = []
            for rec in records:
                job = session.get(JobPosting, rec.job_posting_id) if rec.job_posting_id else None
                items.append(self._record_to_item(rec, job))
            return items

    def create(self, item_in: ApplicationCreate) -> ApplicationItem:
        with Session(engine) as session:
            url = item_in.url or f"https://portal.local/{uuid.uuid4().hex[:8]}"
            job = session.exec(select(JobPosting).where(JobPosting.url == url)).first()
            if not job:
                job = JobPosting(
                    portal=item_in.portal or "generic",
                    external_id=f"manual-{uuid.uuid4().hex[:8]}",
                    title=item_in.role,
                    company=item_in.company,
                    url=url,
                    market="INT_REMOTE",
                    is_remote=True,
                    language_requirements=["English"],
                    description_raw=item_in.notes or "",
                    suitability_score=float(item_in.match_score or 85.0),
                    match_rationale=item_in.notes or "Created from dashboard",
                    status="STAGED",
                )
                session.add(job)
                session.commit()
                session.refresh(job)

            db_status = UI_TO_DB_STATUS.get(item_in.status or "Saved", "STAGED")
            rec = ApplicationRecord(
                job_posting_id=job.id,
                custom_cv_path=item_in.cv_pdf_url or "/api/resumes/resume_qa_automation.pdf",
                cover_letter_text=item_in.notes or "",
                submission_status=db_status,
                applied_at=utc_now(),
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return self._record_to_item(rec, job)

    def update(self, item_id: str, item_update: ApplicationUpdate) -> Optional[ApplicationItem]:
        rec_id_str = str(item_id).replace("app-", "")
        if not rec_id_str.isdigit():
            return None
        with Session(engine) as session:
            rec = session.get(ApplicationRecord, int(rec_id_str))
            if not rec:
                return None
            job = session.get(JobPosting, rec.job_posting_id) if rec.job_posting_id else None

            if item_update.status is not None:
                rec.submission_status = UI_TO_DB_STATUS.get(item_update.status, rec.submission_status)
                if job:
                    job.status = "APPLIED" if rec.submission_status == "SUBMITTED" else (
                        "REJECTED" if rec.submission_status == "REJECTED" else job.status
                    )
                    session.add(job)
            if item_update.notes is not None:
                rec.cover_letter_text = item_update.notes
            if item_update.cv_pdf_url is not None:
                rec.custom_cv_path = item_update.cv_pdf_url
            if job:
                if item_update.company is not None:
                    job.company = item_update.company
                if item_update.role is not None:
                    job.title = item_update.role
                if item_update.match_score is not None:
                    job.suitability_score = float(item_update.match_score)
                session.add(job)

            session.add(rec)
            session.commit()
            session.refresh(rec)
            return self._record_to_item(rec, job)

    def delete(self, item_id: str) -> bool:
        rec_id_str = str(item_id).replace("app-", "")
        if not rec_id_str.isdigit():
            return False
        with Session(engine) as session:
            rec = session.get(ApplicationRecord, int(rec_id_str))
            if not rec:
                return False
            session.delete(rec)
            session.commit()
            return True


tracker_store = TrackerStore()
