import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ..config import GROUND_TRUTH_FILE, SKILLS_MD_FILE
from ..database import engine, init_db
from ..models.db_models import CandidateProfile, utc_now
from ..services.matcher_service import matcher_service

logger = logging.getLogger(__name__)


PROFESSION_MD_PRESETS: Dict[str, Dict[str, str]] = {
    "qa_tech": {
        "id": "qa_tech",
        "label": "💻 QA Automation & Tech Engineer",
        "industry": "qa_tech",
        "content": """# Alex Mercer — Senior QA Automation Engineer & SDET

## Contact & Personal Info
- **Full Name:** Alex Mercer
- **Email:** alex.mercer.dev@gmail.com
- **Phone:** +49 152 98765432
- **Location:** Berlin / Tbilisi (Remote & Abroad Ready)
- **LinkedIn:** https://linkedin.com/in/alex-mercer-qa
- **GitHub:** https://github.com/alex-mercer-automation
- **Availability / Notice Period:** 1 week after offer
- **Salary Expectation:** €85,000 gross/year (or $4,500/mo remote)

## Applicant Summary
I build reliable test automation that helps engineering teams ship faster without breaking production. Over the past 5+ years, I have worked across web, API, and cloud microservices using Playwright, Cypress, and Python.

## Core Skills
- **UI & End-to-End Automation:** Playwright, Cypress, Selenium WebDriver, Appium
- **Programming & Scripting:** Python, TypeScript, JavaScript, Java, SQL, Bash
- **API & Integration Testing:** PyTest, JUnit, Postman, REST Assured, REST API, GraphQL, k6, JMeter
- **CI/CD & DevOps:** GitHub Actions, GitLab CI, Docker, Kubernetes, AWS, Jira, Xray

## Work Experience
### Senior QA Automation Engineer | TechNova Cloud Solutions
*Jan 2023 – Present*
- Built the Playwright + TypeScript end-to-end test suite from scratch, cutting regression time from 14 hours to 35 minutes.
- Integrated parallel CI test runs across GitHub Actions and Docker with 99.4% pipeline reliability.

### QA Engineer / Automation Specialist | Apex Fintech Labs
*Mar 2021 – Dec 2022*
- Automated critical payment and onboarding flows using Cypress and TypeScript for a high-volume banking platform.
"""
    },
    "receptionist_hospitality": {
        "id": "receptionist_hospitality",
        "label": "🏨 Hotel Receptionist & Hospitality",
        "industry": "hospitality_reception",
        "content": """# Nino Kalandadze — Front Desk Receptionist & Guest Relations Specialist

## Contact & Personal Info
- **Full Name:** Nino Kalandadze (ნინო კალანდაძე)
- **Email:** nino.kalandadze.hospitality@gmail.com
- **Phone:** +995 599 12 34 56
- **Location:** Tbilisi, Georgia
- **LinkedIn:** https://linkedin.com/in/nino-kalandadze
- **Availability / Notice Period:** 1 week after offer
- **Salary Expectation:** 2,500 GEL – 3,200 GEL / month

## Applicant Summary
Warm, organized, and detail-oriented Front Desk Receptionist and Hospitality Specialist with 4+ years of experience at 5-star boutique and international hotels. Skilled in Opera PMS, Fidelio, Booking.com/Expedia channel management, VIP guest check-in/check-out, and calm multi-line phone & reservation handling in Georgian, English, and Russian.

## Core Skills
- **Front Desk & Hospitality:** Front Office Operations, Check-in / Check-out, Guest Relations, Concierge Services, VIP Protocol
- **Reservation & Hotel Software:** Opera PMS, Fidelio, Booking.com Extranet, Expedia Partner Central, POS Terminals, MS Office
- **Customer Care & Administration:** Multi-line Phone Etiquette, Cash & Card Billing, Night Audit, Shift Handover, Event Coordination
- **Languages:** Georgian (Native), English (Fluent C1), Russian (Fluent C1)

## Work Experience
### Senior Front Desk Receptionist | Rooms Hotel & Adjara Group
*Tbilisi, Georgia • Feb 2023 – Present*
- Welcomed 120+ international guests daily, managing seamless check-ins, room upgrades, and VIP hospitality requests using Opera PMS.
- Maintained a 9.6/10 Guest Satisfaction Score on Booking.com by resolving guest inquiries on the first contact.

### Front Office & Reservations Agent | Courtyard by Marriott Tbilisi
*Tbilisi, Georgia • May 2021 – Jan 2023*
- Handled phone, email, and walk-in reservations, group bookings, billing reconciliations, and daily front-desk coordination.
"""
    },
    "customer_service": {
        "id": "customer_service",
        "label": "🎧 Customer Service & Support Specialist",
        "industry": "customer_service",
        "content": """# Giorgi Beridze — Senior Customer Service & Client Care Specialist

## Contact & Personal Info
- **Full Name:** Giorgi Beridze (გიორგი ბერიძე)
- **Email:** giorgi.beridze.support@gmail.com
- **Phone:** +995 577 98 76 54
- **Location:** Tbilisi, Georgia / Remote International
- **LinkedIn:** https://linkedin.com/in/giorgi-beridze-cs
- **Availability / Notice Period:** 1 week after offer
- **Salary Expectation:** $1,800 – $2,400 / month (or 3,500 GEL)

## Applicant Summary
Empathetic and high-performing Customer Service & Client Success Specialist with 4+ years of experience supporting international customers across live chat, email, and phone. Expert in Zendesk, Intercom, Salesforce CRM, conflict de-escalation, and maintaining 98%+ CSAT scores.

## Core Skills
- **Customer Support Channels:** Omnichannel Support, Live Chat, Inbound/Outbound Calls, Email Ticketing, Social Media Care
- **CRM & Helpdesk Tools:** Zendesk, Intercom, Salesforce CRM, Freshdesk, HubSpot, Jira Service Desk
- **Soft Skills & Operations:** Conflict De-escalation, Client Retention, SLA Management, KYC Verification, Order & Billing Support
- **Languages:** Georgian (Native), English (C2 Fluent), German (B2)

## Work Experience
### Senior Customer Support Specialist | Global FinTech Care Hub
*Tbilisi / Remote • Jan 2023 – Present*
- Resolved 75+ daily customer inquiries via Zendesk live chat and phone with a 98.4% CSAT rating and <2 minute first-response time.
- Handled VIP account escalations, refund disputes, and onboarding guidance for EU and US clients.

### Customer Care Representative | Evolution / International BPO
*Tbilisi, Georgia • Apr 2021 – Dec 2022*
- Provided 24/7 multilingual customer assistance, troubleshooting account issues and documenting clear FAQ guides for new agents.
"""
    },
    "healthcare_hospital": {
        "id": "healthcare_hospital",
        "label": "🏥 Hospital & Healthcare Coordinator",
        "industry": "healthcare_hospital",
        "content": """# Mariam Maisuradze — Hospital Patient Coordinator & Medical Administrator

## Contact & Personal Info
- **Full Name:** Mariam Maisuradze (მარიამ მაისურაძე)
- **Email:** mariam.maisuradze.med@gmail.com
- **Phone:** +995 595 44 33 22
- **Location:** Tbilisi, Georgia
- **LinkedIn:** https://linkedin.com/in/mariam-maisuradze-med
- **Availability / Notice Period:** 1 week after offer
- **Salary Expectation:** 2,400 GEL – 3,000 GEL / month

## Applicant Summary
Compassionate, composed, and highly organized Hospital Patient Coordinator & Medical Receptionist with 5 years of experience in modern multi-profile clinics and hospitals. Proficient in Electronic Medical Records (EMR/EHR), patient registration, insurance claims verification, doctor appointment scheduling, and reassuring patient communication.

## Core Skills
- **Hospital & Clinical Operations:** Patient Intake & Registration, Triage Coordination, Doctor Appointment Scheduling, Outpatient & Inpatient Flow
- **Medical Systems & Insurance:** EMR / EHR Databases, Health Insurance Authorization, ICD-10 Coding Basics, Medical Billing & Invoicing
- **Patient Care & Compliance:** Medical Confidentiality (HIPAA/GDPR), Calm Crisis Communication, Lab Results Coordination, Bilingual Patient Support

## Work Experience
### Senior Patient Care Coordinator | Evex Hospitals / Caucasus Medical Centre
*Tbilisi, Georgia • Mar 2022 – Present*
- Coordinated daily registration and appointment scheduling for 150+ patients across cardiology, radiology, and surgery departments.
- Managed health insurance pre-authorizations (GPI, Aldagi, Imedi L, State Universal Healthcare) with zero billing discrepancies.

### Medical Receptionist & Clinic Administrator | Todua Clinic
*Tbilisi, Georgia • Jun 2020 – Feb 2022*
- Welcomed patients and families at the main reception desk, maintained digital EHR records, and coordinated urgent diagnostic slots.
"""
    }
}


class GroundTruthStore:
    """
    Relational Database-backed CandidateProfile store (SQLModel / SQLAlchemy).
    Replaces raw JSON persistence with the `candidate_profiles` SQL table while preserving
    full backward compatibility for existing endpoints.
    """

    def __init__(self, filepath=GROUND_TRUTH_FILE, skills_md_path=SKILLS_MD_FILE):
        self.filepath = filepath
        self.skills_md_path = skills_md_path
        init_db()
        self._ensure_seeded()

    def _load_seed_json(self) -> Dict[str, Any]:
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading seed JSON: {e}")
        return {}

    def _ensure_seeded(self) -> CandidateProfile:
        with Session(engine) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            if profile:
                return profile

            raw_md = ""
            if self.skills_md_path.exists():
                raw_md = self.skills_md_path.read_text(encoding="utf-8")
            if not raw_md:
                raw_md = PROFESSION_MD_PRESETS["qa_tech"]["content"]

            seed_gt = self._load_seed_json()
            taxonomy = matcher_service.parse_skills_markdown(raw_md)
            taxonomy["ground_truth_vault"] = seed_gt

            profile = CandidateProfile(
                raw_markdown=raw_md,
                parsed_skills=taxonomy,
                updated_at=utc_now(),
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def get_profile_record(self) -> CandidateProfile:
        return self._ensure_seeded()

    def get_profession_presets(self) -> Dict[str, Dict[str, str]]:
        return PROFESSION_MD_PRESETS

    def get_preset_md(self, preset_id: str) -> str:
        preset = PROFESSION_MD_PRESETS.get(preset_id)
        if not preset:
            raise ValueError(f"Unknown preset_id: {preset_id}")
        return preset["content"]

    def get_data(self) -> Dict[str, Any]:
        """Returns the full candidate vault backed by CandidateProfile in SQLite/PostgreSQL."""
        profile = self.get_profile_record()
        vault = dict(profile.parsed_skills.get("ground_truth_vault") or self._load_seed_json())
        vault["skills_md_raw"] = profile.raw_markdown
        vault["parsed_skills_taxonomy"] = {
            k: v for k, v in profile.parsed_skills.items() if k != "ground_truth_vault"
        }
        return vault

    def update_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists updated candidate vault into CandidateProfile in the relational DB."""
        save_copy = dict(data)
        raw_md = save_copy.pop("skills_md_raw", None)
        save_copy.pop("parsed_skills_taxonomy", None)

        with Session(engine) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            if not profile:
                profile = self._ensure_seeded()
                profile = session.get(CandidateProfile, profile.id)

            if raw_md is not None:
                profile.raw_markdown = raw_md
                try:
                    self.skills_md_path.write_text(raw_md, encoding="utf-8")
                except Exception:
                    pass

            taxonomy = matcher_service.parse_skills_markdown(profile.raw_markdown)
            taxonomy["ground_truth_vault"] = save_copy
            profile.parsed_skills = taxonomy
            profile.updated_at = utc_now()
            session.add(profile)
            session.commit()

        return self.get_data()

    def get_skills_md(self) -> str:
        """Reads the candidate's raw_markdown directly from CandidateProfile in the relational database."""
        profile = self.get_profile_record()
        return profile.raw_markdown or ""

    def parse_profile_from_md(self, md_content: str) -> Dict[str, Any]:
        """
        Extracts name, headline, email, phone, location, summary, skills,
        and work history from any English or Georgian .md skills file.
        """
        result: Dict[str, Any] = {}
        lines = md_content.splitlines()

        for line in lines:
            s = line.strip()
            if s.startswith("# "):
                h1 = s[2:].strip()
                parts = re.split(r"\s+[—–-]\s+", h1, maxsplit=1)
                result["full_name"] = parts[0].strip()
                if len(parts) > 1:
                    result["headline"] = parts[1].strip()
                break

        email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", md_content)
        if email_m:
            result["email"] = email_m.group(0)

        phone_m = re.search(r"(?:Phone|ტელეფონი|Tel)\**\s*:\**\s*([+\d\s()-]{7,22})", md_content, re.I)
        if phone_m:
            result["phone"] = phone_m.group(1).strip()

        name_m = re.search(r"(?:Full Name|სახელი და გვარი|Name)\**\s*:\**\s*([^\n]+)", md_content, re.I)
        if name_m:
            result["full_name"] = name_m.group(1).strip()

        summary_lines = []
        in_summary = False
        for line in lines:
            s = line.strip()
            if s.startswith("##"):
                in_summary = any(w in s.lower() for w in ["summary", "about", "შესახებ", "მიმოხილვა", "პროფილი"])
                continue
            if in_summary and s and not s.startswith("#"):
                summary_lines.append(s)
        if summary_lines:
            result["summary"] = " ".join(summary_lines)

        result["skills"] = self.extract_skills_from_md(md_content)

        work_history = []
        in_exp = False
        current_job = None
        for line in lines:
            s = line.strip()
            if s.startswith("## ") and not s.startswith("### "):
                in_exp = any(w in s.lower() for w in ["experience", "history", "work", "გამოცდილება", "სამუშაო"])
                if not in_exp and current_job:
                    work_history.append(current_job)
                    current_job = None
                continue
            if in_exp:
                if s.startswith("### "):
                    if current_job:
                        work_history.append(current_job)
                    header = s[4:].strip()
                    parts = [p.strip() for p in re.split(r"[|@—–]", header, maxsplit=1)]
                    role = parts[0]
                    comp = parts[1] if len(parts) > 1 else "Organization"
                    current_job = {
                        "role": role,
                        "company": comp,
                        "location": "Tbilisi / Remote",
                        "start_date": "2021",
                        "end_date": "Present",
                        "highlights": []
                    }
                elif current_job and s.startswith(("*", "-")) and not s.startswith("* ") and s.endswith("*"):
                    meta = s.strip("* ")
                    current_job["start_date"] = meta
                    current_job["end_date"] = ""
                elif current_job and s.startswith(("-", "*")):
                    bullet = re.sub(r"^[-*]\s*", "", s).strip()
                    if bullet:
                        current_job["highlights"].append(bullet)
        if current_job:
            work_history.append(current_job)
        if work_history:
            result["work_history"] = work_history

        return result

    def ingest_skills_markdown(self, md_content: str) -> CandidateProfile:
        """
        Ingests a skills.md file into the CandidateProfile relational table,
        computing structured QA/SDET + multi-industry taxonomy via MatcherService/Gemini.
        """
        try:
            self.skills_md_path.write_text(md_content, encoding="utf-8")
        except Exception:
            pass

        parsed = self.parse_profile_from_md(md_content)
        taxonomy = matcher_service.parse_skills_markdown(md_content)

        gt = self.get_data()
        gt.pop("skills_md_raw", None)
        gt.pop("parsed_skills_taxonomy", None)

        cand = gt.setdefault("candidate", {})
        if parsed.get("full_name"):
            cand["full_name"] = parsed["full_name"]
            name_parts = parsed["full_name"].split()
            cand["first_name"] = name_parts[0]
            cand["last_name"] = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        if parsed.get("headline"):
            cand["headline"] = parsed["headline"]
        if parsed.get("email"):
            cand["email"] = parsed["email"]
        if parsed.get("phone"):
            cand["phone"] = parsed["phone"]
        if parsed.get("skills"):
            gt.setdefault("skills", {})["core"] = parsed["skills"]
        if parsed.get("work_history"):
            gt["work_history"] = parsed["work_history"]
        cand.setdefault("compensation", {})["notice_period"] = "1 week after offer"

        taxonomy["ground_truth_vault"] = gt

        with Session(engine) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            if profile:
                profile.raw_markdown = md_content
                profile.parsed_skills = taxonomy
                profile.updated_at = utc_now()
            else:
                profile = CandidateProfile(
                    raw_markdown=md_content,
                    parsed_skills=taxonomy,
                    updated_at=utc_now(),
                )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def save_skills_md(self, md_content: str) -> Dict[str, Any]:
        """Saves skills.md into CandidateProfile and returns the updated ground truth dictionary."""
        self.ingest_skills_markdown(md_content)
        return self.get_data()

    def extract_skills_from_md(self, md_content: str) -> List[str]:
        """Extracts individual skills from English or Georgian markdown bullet lists."""
        skills = []
        in_skills_section = False
        for line in md_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("##"):
                header_lower = stripped.lower()
                in_skills_section = any(
                    w in header_lower for w in ["skill", "stack", "tech", "უნარ", "კომპეტენც", "ენები"]
                )
                continue
            if in_skills_section and stripped.startswith(("-", "*")):
                cleaned = re.sub(r"^[-*]\s*(\*\*.*?\*\*:?)?\s*", "", stripped)
                parts = [p.strip() for p in re.split(r"[,;/]", cleaned) if p.strip()]
                for p in parts:
                    if 1 < len(p) <= 55 and p not in skills:
                        skills.append(p)
        return skills

    def get_candidate(self) -> Dict[str, Any]:
        return self.get_data().get("candidate", {})

    def get_skills(self) -> Dict[str, Any]:
        return self.get_data().get("skills", {})

    def get_work_history(self) -> list:
        return self.get_data().get("work_history", [])

    def get_cv_variants(self) -> Dict[str, Any]:
        return self.get_data().get("cv_variants", {})

    def get_faq_bank(self) -> list:
        return self.get_data().get("faq_bank", [])


ground_truth_store = GroundTruthStore()
