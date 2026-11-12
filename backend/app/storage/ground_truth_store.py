import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ..config import GROUND_TRUTH_FILE, SKILLS_MD_FILE
from ..database import engine, init_db
from ..models.db_models import CandidateProfile, utc_now
from ..services.matcher_service import matcher_service, dedupe_skills_case_insensitive

logger = logging.getLogger(__name__)

_storage_lock = threading.Lock()


def atomic_write_text(filepath: Path, content: str, encoding: str = "utf-8") -> None:
    """Performs thread-safe, atomic file writes using temp file + atomic os.replace."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock:
        temp_file = filepath.with_suffix(f".tmp.{os.getpid()}")
        try:
            temp_file.write_text(content, encoding=encoding)
            os.replace(temp_file, filepath)
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            logger.warning(f"Atomic file write warning for {filepath}: {e}")


PROFESSION_MD_PRESETS: Dict[str, Dict[str, str]] = {
    "qa_tech": {
        "id": "qa_tech",
        "label": "💻 QA Automation & Tech Engineer",
        "industry": "qa_tech",
        "content": """# Sample QA Automation & API Testing Engineer

## Contact & Personal Info
- **Full Name:** Sample QA Candidate
- **Email:** qa.candidate@example.com
- **Phone:** +000 000 0000
- **Location:** Tbilisi, Georgia (Remote & Abroad Ready)
- **LinkedIn:** https://linkedin.com/in/example-candidate
- **GitHub:** https://github.com/example-candidate
- **Availability / Notice Period:** 1 week after offer
- **Salary Expectation:** $3,000 - $3,500/mo remote

## Applicant Summary
I build reliable test automation and API test suites that help engineering teams ship faster with high quality. Over the past 1.5 years, I have engineered test suites across web and API architectures using Playwright, Cypress, Python, and Postman.

## Core Skills
- **UI & End-to-End Automation:** Playwright, Cypress, Selenium WebDriver, Appium
- **Programming & Scripting:** Python, TypeScript, JavaScript, SQL, Bash
- **API & Integration Testing:** PyTest, JUnit, Postman, REST Assured, REST API, GraphQL, k6
- **CI/CD & DevOps:** GitHub Actions, Docker, Git, Jira

## Work Experience & Portfolio
### QA Automation Engineer / Test Designer | Portfolio Project
*Jan 2023 – Present*
- Engineered comprehensive REST API test framework in Postman and Playwright with automated boundary value analysis and JSON schema validation.
- Built automated test runners with CI/CD integration, cutting manual verification cycles significantly.
"""
    },
    "receptionist_hospitality": {
        "id": "receptionist_hospitality",
        "label": "🏨 Hotel Receptionist & Hospitality",
        "industry": "hospitality_reception",
        "content": """# Nino Kalandadze — Front Desk Receptionist & Guest Relations Specialist

## Contact & Personal Info
- **Full Name:** Nino Kalandadze (ნინო კალანდაძე)
- **Email:** hospitality.candidate@example.com
- **Phone:** +000 000 0000
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
- **Email:** support.candidate@example.com
- **Phone:** +000 000 0000
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
- **Email:** medical.candidate@example.com
- **Phone:** +000 000 0000
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
            if profile and profile.full_name:
                return profile

        from ..services.profile_service import profile_service
        raw_md = ""
        if self.skills_md_path.exists():
            raw_md = self.skills_md_path.read_text(encoding="utf-8")
        if not raw_md:
            raw_md = PROFESSION_MD_PRESETS["qa_tech"]["content"]

        return profile_service.upsert_candidate_profile(raw_md, mark_uploaded=False)

    def get_profile_record(self) -> CandidateProfile:
        return self._ensure_seeded()

    def get_profession_presets(self) -> Dict[str, Dict[str, str]]:
        return PROFESSION_MD_PRESETS

    def get_preset_md(self, preset_id: str) -> str:
        preset = PROFESSION_MD_PRESETS.get(preset_id)
        if not preset:
            raise ValueError(f"Unknown preset_id: {preset_id}")
        return preset["content"]

    def _default_faq_bank(self, cand: Dict[str, Any]) -> List[Dict[str, Any]]:
        loc = cand.get("location", {})
        city = loc.get("city", "Tbilisi") if isinstance(loc, dict) else "Tbilisi"
        return [
            {
                "question_trigger": "notice period / earliest start date",
                "tags": ["availability", "notice", "start_date"],
                "answer": "Available to start 1 week after offer acceptance (or immediately upon contract signing).",
            },
            {
                "question_trigger": "work authorization / remote B2B & visa status",
                "tags": ["visa", "b2b", "remote", "authorization"],
                "answer": f"Based in {city}, Georgia; authorized to work locally and collaborate globally on remote B2B / independent contractor engagements without employer relocation sponsorship.",
            },
            {
                "question_trigger": "remote collaboration / timezone overlap",
                "tags": ["remote", "timezone", "communication"],
                "answer": "Comfortable working asynchronously and overlapping core EU (CET/EET) and US morning business hours with clear English communication.",
            },
        ]

    def _normalize_vault(self, vault: Dict[str, Any], profile: CandidateProfile) -> Dict[str, Any]:
        """Guarantees complete, null-safe vault structure so Profile Vault / Visas / FAQ Bank never crash."""
        data = dict(vault or {})
        raw_md = profile.raw_markdown or ""
        parsed_md = self.parse_profile_from_md(raw_md) if raw_md else {}
        ps = dict(profile.parsed_skills or {})

        cand = dict(data.get("candidate") or {})
        full_name = cand.get("full_name") or profile.full_name or "Candidate"
        parts = full_name.split()
        cand.setdefault("first_name", parts[0] if parts else "Candidate")
        cand.setdefault("last_name", " ".join(parts[1:]) if len(parts) > 1 else "")
        cand["full_name"] = full_name
        cand.setdefault("headline", ps.get("headline") or parsed_md.get("headline") or "QA Engineer")
        cand.setdefault("email", profile.email or "candidate@example.com")
        cand.setdefault("phone", profile.phone or "+000 000 0000")

        loc = cand.get("location")
        if not isinstance(loc, dict):
            loc = {}
        loc.setdefault("city", "Tbilisi")
        loc.setdefault("country", "Georgia")
        loc.setdefault("timezone", "Asia/Tbilisi (UTC+4)")
        loc.setdefault("open_to_relocation", True)
        loc.setdefault("remote_preference", "Remote / Hybrid / Georgia")
        cand["location"] = loc

        links = cand.get("links")
        if not isinstance(links, dict):
            links = {}
        links.setdefault("linkedin", profile.linkedin_url or "")
        links.setdefault("github", profile.github_url or "")
        links.setdefault("portfolio", "")
        cand["links"] = links

        wa = cand.get("work_authorization")
        if not isinstance(wa, dict):
            wa = {}
        wa.setdefault("citizenship", ["Georgia"])
        wa.setdefault("eu_work_permit", False)
        wa.setdefault("requires_eu_visa", True)
        wa.setdefault("us_work_authorization", "Remote B2B Contractor (No US Work Permit)")
        wa.setdefault("requires_us_visa_sponsorship", True)
        wa.setdefault("uk_work_authorization", "Remote B2B Contractor")
        wa.setdefault("security_clearance", False)
        cand["work_authorization"] = wa

        comp = cand.get("compensation")
        if not isinstance(comp, dict):
            comp = {}
        if not comp.get("expected_salary_eur"):
            comp["expected_salary_eur"] = 38000
        if not comp.get("min_salary_eur"):
            comp["min_salary_eur"] = 32000
        if not comp.get("expected_salary_usd"):
            comp["expected_salary_usd"] = 42000
        comp.setdefault("notice_period", "1 week after offer")
        cand["compensation"] = comp

        langs = cand.get("languages")
        if not isinstance(langs, list) or not langs:
            spoken = ps.get("spoken_languages") or ["English", "Georgian"]
            langs = [{"language": str(l), "proficiency": "Fluent / Native"} for l in spoken]
        cand["languages"] = langs
        data["candidate"] = cand

        # Skills normalization & clean deduplication
        skills = dict(data.get("skills") or {})
        raw_core = skills.get("core") or ps.get("all_skills") or []
        skills["core"] = dedupe_skills_case_insensitive([str(x) for x in raw_core])
        skills["secondary"] = dedupe_skills_case_insensitive([str(x) for x in (skills.get("secondary") or [])])
        data["skills"] = skills

        wh = data.get("work_history")
        if not isinstance(wh, list) or not wh:
            wh = parsed_md.get("work_history") or []
        cleaned_wh = []
        for job in wh:
            if not isinstance(job, dict):
                continue
            jcopy = dict(job)
            jcopy["highlights"] = [
                str(b).strip()
                for b in (job.get("highlights") or [])
                if b and str(b).strip() and not re.fullmatch(r"[-*_•–—.\s]+", str(b).strip())
            ]
            cleaned_wh.append(jcopy)
        data["work_history"] = cleaned_wh

        edu = data.get("education")
        if not isinstance(edu, list):
            edu = []
        data["education"] = edu

        faq = data.get("faq_bank")
        if not isinstance(faq, list) or not faq:
            faq = self._default_faq_bank(cand)
        data["faq_bank"] = faq

        data.setdefault("cv_variants", {})
        data["skills_md_raw"] = raw_md
        data["parsed_skills_taxonomy"] = {k: v for k, v in ps.items() if k != "ground_truth_vault"}
        return data

    def get_data(self) -> Dict[str, Any]:
        """Returns the full candidate vault backed by CandidateProfile in SQLite/PostgreSQL."""
        profile = self.get_profile_record()
        raw_vault = dict(profile.parsed_skills.get("ground_truth_vault") or self._load_seed_json())
        return self._normalize_vault(raw_vault, profile)

    def update_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists updated candidate vault into CandidateProfile in the relational DB (encrypted at rest)."""
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

            cand_in = save_copy.get("candidate")
            if isinstance(cand_in, dict):
                if cand_in.get("full_name"):
                    profile.full_name = str(cand_in["full_name"])
                elif cand_in.get("first_name") or cand_in.get("last_name"):
                    profile.full_name = f"{cand_in.get('first_name', '')} {cand_in.get('last_name', '')}".strip()
                if cand_in.get("email"):
                    profile.email = str(cand_in["email"])
                if cand_in.get("phone"):
                    profile.phone = str(cand_in["phone"])

            existing_ps = dict(profile.parsed_skills or {})
            taxonomy = matcher_service.parse_skills_markdown(profile.raw_markdown)
            # Preserve user-edited skills if provided in Profile Vault
            if isinstance(save_copy.get("skills"), dict) and isinstance(save_copy["skills"].get("core"), list):
                cleaned_core = dedupe_skills_case_insensitive([str(x) for x in save_copy["skills"]["core"]])
                save_copy["skills"]["core"] = cleaned_core
                taxonomy["all_skills"] = cleaned_core
            if "user_uploaded" in existing_ps:
                taxonomy["user_uploaded"] = existing_ps["user_uploaded"]
            if "owner_email" in existing_ps:
                taxonomy["owner_email"] = existing_ps["owner_email"]
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

        phone_m = re.search(r"(?:Phone|ტელეფონი|Tel)\**\s*:\**\s*([+\d \t()-]{7,22})", md_content, re.I)
        if phone_m:
            result["phone"] = phone_m.group(1).strip(" -\t\r\n")

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
                # Never treat Markdown horizontal separators (---, ***, ___) as bullet items!
                if re.fullmatch(r"[-*_=\s]{2,}", s):
                    continue
                if s.startswith("### "):
                    if current_job:
                        work_history.append(current_job)
                    header = re.sub(r"[*_`]+", "", s[4:]).strip()
                    parts = [p.strip() for p in re.split(r"[|@—–]", header, maxsplit=1)]
                    role = parts[0]
                    comp = parts[1] if len(parts) > 1 else "Organization"
                    current_job = {
                        "role": role,
                        "company": comp,
                        "location": "Tbilisi / Remote",
                        "start_date": "",
                        "end_date": "Present",
                        "highlights": []
                    }
                elif current_job and (
                    (s.startswith(("*", "-")) and not s.startswith("* ") and s.endswith("*"))
                    or re.search(r"(?:20\d{2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|present)", s, re.I)
                    and len(s) < 90
                    and "•" in s or ("*" in s and ("–" in s or "-" in s) and len(s) < 90)
                ):
                    meta = re.sub(r"[*_`]+", "", s).strip()
                    if "•" in meta:
                        left, right = [x.strip() for x in meta.split("•", 1)]
                        if re.search(r"20\d{2}", right):
                            current_job["location"] = left or current_job["location"]
                            current_job["start_date"] = right
                            current_job["end_date"] = ""
                        else:
                            current_job["company"] = left or current_job["company"]
                            current_job["location"] = right
                    else:
                        current_job["start_date"] = meta
                        current_job["end_date"] = ""
                elif current_job and s.startswith(("-", "*")):
                    bullet = re.sub(r"^[-*]\s*", "", s).strip()
                    bullet = re.sub(r"[*_`]+", "", bullet).strip()
                    if bullet and not re.fullmatch(r"[-*_•–—.\s]+", bullet):
                        current_job["highlights"].append(bullet)
        if current_job:
            work_history.append(current_job)
        if work_history:
            result["work_history"] = work_history

        return result

    def ingest_skills_markdown(self, md_content: str) -> CandidateProfile:
        """
        Ingests a skills.md file into the CandidateProfile relational table via ProfileService,
        extracting personal info, QA/SDET taxonomy, and work history.
        """
        from ..services.profile_service import profile_service
        profile = profile_service.upsert_candidate_profile(md_content)
        parsed = self.parse_profile_from_md(md_content)
        if parsed.get("work_history"):
            with Session(engine, expire_on_commit=False) as session:
                db_prof = session.get(CandidateProfile, profile.id)
                if db_prof:
                    skills_copy = dict(db_prof.parsed_skills)
                    vault = dict(skills_copy.get("ground_truth_vault") or {})
                    vault["work_history"] = parsed["work_history"]
                    skills_copy["ground_truth_vault"] = vault
                    db_prof.parsed_skills = skills_copy
                    session.add(db_prof)
                    session.commit()
                    session.refresh(db_prof)
                    return db_prof
        return profile

    def save_skills_md(self, md_content: str) -> Dict[str, Any]:
        """Saves skills.md into CandidateProfile and returns the updated ground truth dictionary."""
        self.ingest_skills_markdown(md_content)
        return self.get_data()

    def extract_skills_from_md(self, md_content: str) -> List[str]:
        """Extracts clean, deduplicated technical & domain skills from markdown via MatcherService."""
        if not md_content:
            return []
        taxonomy = matcher_service.parse_skills_markdown(md_content)
        return list(taxonomy.get("all_skills") or [])

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
