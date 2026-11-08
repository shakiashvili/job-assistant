import logging
from typing import List
from fastapi import APIRouter, HTTPException
from ..models.schemas import JobAuditRequest, JobAuditResponse, PortalVacancyItem
from ..services.audit_service import audit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Job Audit & Portal Vacancies"])


CURATED_PORTAL_VACANCIES: List[PortalVacancyItem] = [
    PortalVacancyItem(
        id="vac-hosp-1",
        title="Front Desk Receptionist / Guest Relations Officer (მიმღები-რეცეფციონისტი)",
        company="Rooms Hotel Tbilisi (Adjara Group)",
        portal="jobs.ge",
        industry="receptionist_hospitality",
        location="Tbilisi, Georgia",
        salary="2,200 – 2,800 GEL / mo + Bonuses",
        url="https://jobs.ge/ge/?view=jobs&id=549201",
        mock_url="http://localhost:8000/mock-portals/jobs_ge_sample.html",
        company_reviews_count=62,
        company_rating=4.7,
        requires_motivational_letter=False,
        description=(
            "Front Desk Receptionist / Guest Relations Officer at Rooms Hotel Tbilisi (listed on Jobs.ge & HR.ge). "
            "Responsibilities & Requirements: Guest Check-in / Check-out, Opera PMS, Fidelio, Booking.com & Expedia Extranet, "
            "Reservation Management, VIP Guest Relations, POS Terminal & Cash Handling, Switchboard & Multiline Phone, "
            "Conflict Resolution, Georgian (Native) and English (Fluent). სასტუმროს მიმღები რეცეფციონისტი."
        )
    ),
    PortalVacancyItem(
        id="vac-med-1",
        title="Hospital Patient Coordinator / Medical Receptionist (სამედიცინო კოორდინატორი)",
        company="Evex Hospitals / Todua Clinic",
        portal="hr.ge",
        industry="healthcare_hospital",
        location="Tbilisi, Georgia",
        salary="2,000 – 2,600 GEL / mo",
        url="https://hr.ge/announcement/401822/hospital-patient-coordinator",
        mock_url="http://localhost:8000/mock-portals/jobs_ge_sample.html",
        company_reviews_count=54,
        company_rating=4.3,
        requires_motivational_letter=False,
        description=(
            "Hospital Patient Coordinator & Medical Receptionist at Evex Hospitals (HR.ge / Jobs.ge). "
            "Requirements: Patient Registration, EMR / EHR Systems, Appointment Scheduling, Insurance Verification, "
            "Medical Front Desk, Triage Coordination, HIPAA & Patient Privacy, Medical Billing / Copay, Customer Care, "
            "Georgian & English communication. კლინიკის პაციენტთა კოორდინატორი / სამედიცინო რეგისტრატორი."
        )
    ),
    PortalVacancyItem(
        id="vac-cs-1",
        title="Senior Customer Service & Client Care Specialist (მომხმარებელთა მხარდაჭერა)",
        company="TBC Bank / Evolution Georgia",
        portal="jobs.ge",
        industry="customer_service",
        location="Tbilisi / Remote Hybrid",
        salary="$1,400 – $2,100 / mo",
        url="https://jobs.ge/en/?view=jobs&id=548810",
        mock_url="http://localhost:8000/mock-portals/jobs_ge_sample.html",
        company_reviews_count=89,
        company_rating=4.4,
        requires_motivational_letter=False,
        description=(
            "Senior Customer Service & Omnichannel Support Specialist (Jobs.ge / HeadHunter.ge). "
            "Requirements: Customer Support, Omnichannel Support (Live Chat, Email, Phone), Zendesk, Intercom, Salesforce CRM, "
            "De-escalation & Conflict Resolution, SLA Management, CSAT / NPS Optimization, Ticketing Systems, Fluent English & Georgian."
        )
    ),
    PortalVacancyItem(
        id="vac-dou-1",
        title="Senior QA Automation Engineer (Playwright / Python)",
        company="MacPaw",
        portal="dou.ua",
        industry="qa_tech",
        location="Remote (Ukraine / EU / Georgia / Worldwide)",
        salary="$4,200 – $5,500 / mo",
        url="https://jobs.dou.ua/companies/macpaw/vacancies/289104/",
        mock_url="http://localhost:8000/mock-portals/dou_sample.html",
        company_reviews_count=142,
        company_rating=4.8,
        requires_motivational_letter=True,
        description=(
            "Senior QA Automation Engineer at MacPaw (DOU.ua). Requirements: 4+ years experience in Playwright or Cypress, "
            "Python, TypeScript, PyTest, REST API, GraphQL, GitHub Actions, Docker, English Upper-Intermediate+. "
            "Note: DOU.ua requires an additional personalized Motivational Letter."
        )
    ),
    PortalVacancyItem(
        id="vac-djinni-1",
        title="Lead SDET / QA Automation Engineer",
        company="Grammarly",
        portal="djinni.co",
        industry="qa_tech",
        location="Full Remote (Abroad / Worldwide)",
        salary="$5,000 – $6,200 / mo",
        url="https://djinni.co/jobs/654321-lead-sdet-playwright/",
        mock_url="http://localhost:8000/mock-portals/djinni_sample.html",
        company_reviews_count=215,
        company_rating=4.6,
        requires_motivational_letter=False,
        description=(
            "Lead SDET / QA Automation Engineer at Grammarly via Djinni.co. Stack: Playwright, TypeScript, Python, "
            "PyTest, Docker, GitHub Actions, AWS, k6 load testing. Full remote abroad contract."
        )
    ),
    PortalVacancyItem(
        id="vac-jobsge-1",
        title="Senior QA Automation Engineer (Remote / Tbilisi)",
        company="TBC Digital",
        portal="jobs.ge",
        industry="qa_tech",
        location="Tbilisi, Georgia / Remote",
        salary="$4,000 – $5,000 / mo",
        url="https://jobs.ge/en/?view=jobs&id=541092",
        mock_url="http://localhost:8000/mock-portals/jobs_ge_sample.html",
        company_reviews_count=89,
        company_rating=4.4,
        requires_motivational_letter=False,
        description=(
            "Senior QA Automation Engineer at TBC Digital (listed on Jobs.ge, HR.ge, and HeadHunter.ge). "
            "Requirements: Playwright, Cypress, Python, PyTest, REST API, SQL, Docker, CI/CD pipelines."
        )
    ),
    PortalVacancyItem(
        id="vac-hhge-1",
        title="International Hospitality & VIP Concierge Coordinator",
        company="Marriott International Tbilisi",
        portal="headhunter.ge",
        industry="receptionist_hospitality",
        location="Tbilisi, Georgia",
        salary="2,500 – 3,200 GEL / mo",
        url="https://headhunter.ge/vacancy/9841990",
        mock_url="http://localhost:8000/mock-portals/jobs_ge_sample.html",
        company_reviews_count=420,
        company_rating=4.5,
        requires_motivational_letter=False,
        description=(
            "International Hospitality & Front Office Receptionist at Marriott Tbilisi (HeadHunter.ge / HR.ge). "
            "Requirements: Opera PMS, Guest Check-in / Check-out, Reservation Management, Concierge & Guest Services, "
            "VIP Guest Relations, POS & Billing, English & Georgian fluency."
        )
    ),
    PortalVacancyItem(
        id="vac-justjoin-1",
        title="Senior QA Automation Engineer (100% Remote B2B)",
        company="Allegro",
        portal="justjoin.it",
        industry="qa_tech",
        location="Remote EU / Abroad B2B",
        salary="€6,500 – €8,000 / mo",
        url="https://justjoin.it/offers/allegro-senior-qa-automation-engineer",
        mock_url="http://localhost:8000/mock-portals/justjoin_sample.html",
        company_reviews_count=180,
        company_rating=4.4,
        requires_motivational_letter=False,
        description=(
            "Senior QA Automation Engineer at Allegro via JustJoin.it (100% Remote B2B). "
            "Stack: Playwright, TypeScript, Python, PyTest, Docker, GitHub Actions, k6, Kubernetes."
        )
    ),
    PortalVacancyItem(
        id="vac-gh-1",
        title="Senior QA Automation Engineer",
        company="CloudScale Technologies",
        portal="greenhouse",
        industry="qa_tech",
        location="Berlin / Remote EU",
        salary="€85,000 / yr",
        url="https://boards.greenhouse.io/cloudscale/jobs/7123910",
        mock_url="http://localhost:8000/mock-portals/greenhouse_sample.html",
        company_reviews_count=48,
        company_rating=4.3,
        requires_motivational_letter=False,
        description=(
            "Senior QA Automation Engineer at CloudScale Technologies (Greenhouse). "
            "4+ years Playwright, Cypress, Python, TypeScript, REST API, GitHub Actions, Docker."
        )
    ),
    PortalVacancyItem(
        id="vac-lever-1",
        title="Senior SDET / QA Automation Engineer",
        company="DataSphere Technologies",
        portal="lever",
        industry="qa_tech",
        location="Remote EU / CET",
        salary="€88,000 / yr",
        url="https://jobs.lever.co/datasphere/senior-sdet",
        mock_url="http://localhost:8000/mock-portals/lever_sample.html",
        company_reviews_count=64,
        company_rating=4.5,
        requires_motivational_letter=False,
        description=(
            "Senior SDET at DataSphere Technologies (Lever). "
            "3-5+ years Python, TypeScript, Playwright, Cypress, REST APIs, SQL, Docker, CI/CD."
        )
    ),
]


@router.get("/vacancies", response_model=List[PortalVacancyItem])
def list_portal_vacancies():
    """Returns multi-industry vacancies (QA/Tech, Receptionist & Hospitality, Customer Service, Hospital/Healthcare) across djinni.co, dou.ua, jobs.ge, hr.ge, headhunter.ge, justjoin.it, Greenhouse, and Lever."""
    return CURATED_PORTAL_VACANCIES


@router.post("/audit-job", response_model=JobAuditResponse)
async def audit_job_endpoint(request: JobAuditRequest):
    """
    Audits a job posting from raw text or job URL across any industry, validates company reviews (3+ gate),
    returns Skills / ATS / Recruiter match scores + Gaps, and generates a tailored
    Human-Tone PDF & HTML CV in English ('en') or Georgian ('ka') based on candidate_skills.md.
    """
    if not request.raw_text and not request.job_url:
        raise HTTPException(
            status_code=400,
            detail="Either 'raw_text' or 'job_url' must be provided."
        )

    try:
        response = await audit_service.audit_job(
            raw_text=request.raw_text,
            job_url=request.job_url,
            variant=request.variant or "qa_automation",
            skills_md_override=request.skills_md_override,
            cv_language=request.cv_language or "en",
        )
        return response
    except Exception as e:
        logger.error(f"Failed to audit job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Job audit failed: {str(e)}")
