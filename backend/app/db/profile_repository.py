import logging
import re
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ..config import SKILLS_MD_FILE
from .database import engine, init_db
from .models import CandidateProfile, utc_now
from ..services.matcher_service import matcher_service, dedupe_skills_case_insensitive

logger = logging.getLogger(__name__)

# Minimal sample templates retained ONLY for automated backend test suites
PROFESSION_MD_PRESETS: Dict[str, Dict[str, str]] = {
    "qa_tech": {
        "id": "qa_tech",
        "label": "QA Automation & Tech Engineer",
        "industry": "qa_tech",
        "content": """# Sample QA Automation & API Testing Engineer

## Contact & Personal Info
- **Full Name:** Sample QA Candidate
- **Email:** qa.candidate@example.com
- **Phone:** +000 000 0000
- **Location:** Remote & International
- **LinkedIn:** https://linkedin.com/in/example-candidate
- **GitHub:** https://github.com/example-candidate
- **Availability / Notice Period:** 1 week after offer

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
""",
    },
    "receptionist_hospitality": {
        "id": "receptionist_hospitality",
        "label": "Hotel Receptionist & Hospitality",
        "industry": "hospitality_reception",
        "content": """# Nino Kalandadze — Front Desk Receptionist & Guest Relations Specialist

## Contact & Personal Info
- **Full Name:** Nino Kalandadze (ნინო კალანდაძე)
- **Email:** hospitality.candidate@example.com
- **Location:** Tbilisi, Georgia
- **LinkedIn:** https://linkedin.com/in/nino-kalandadze
- **Availability / Notice Period:** 1 week after offer

## Applicant Summary
Front Desk Receptionist and Hospitality Specialist with 4+ years of experience at 5-star boutique and international hotels. Skilled in Opera PMS, Fidelio, Booking.com/Expedia channel management, VIP guest check-in/check-out, and reservation handling in Georgian, English, and Russian.

## Core Skills
- **Front Desk & Hospitality:** Front Office Operations, Check-in / Check-out, Guest Relations, Concierge Services, VIP Protocol
- **Reservation & Hotel Software:** Opera PMS, Fidelio, Booking.com Extranet, Expedia Partner Central, POS Terminals, MS Office
- **Languages:** Georgian (Native), English (Fluent C1), Russian (Fluent C1)
""",
    },
    "customer_service": {
        "id": "customer_service",
        "label": "Customer Service & Support Specialist",
        "industry": "customer_service",
        "content": """# Giorgi Beridze — Senior Customer Service & Client Care Specialist

## Contact & Personal Info
- **Full Name:** Giorgi Beridze (გიორგი ბერიძე)
- **Email:** support.candidate@example.com
- **Location:** Tbilisi, Georgia / Remote International

## Core Skills
- **Customer Support Channels:** Omnichannel Support, Live Chat, Inbound/Outbound Calls, Email Ticketing
- **CRM & Helpdesk Tools:** Zendesk, Intercom, Salesforce CRM, Freshdesk, HubSpot
- **Languages:** Georgian (Native), English (C2 Fluent), German (B2)
""",
    },
    "healthcare_hospital": {
        "id": "healthcare_hospital",
        "label": "Hospital & Healthcare Coordinator",
        "industry": "healthcare_hospital",
        "content": """# Mariam Maisuradze — Hospital Patient Coordinator & Medical Administrator

## Contact & Personal Info
- **Full Name:** Mariam Maisuradze (მარიამ მაისურაძე)
- **Email:** medical.candidate@example.com
- **Location:** Tbilisi, Georgia

## Core Skills
- **Hospital & Clinical Operations:** Patient Intake & Registration, Triage Coordination, Doctor Appointment Scheduling
- **Medical Systems & Insurance:** EMR / EHR Databases, Health Insurance Authorization, ICD-10 Coding Basics
""",
    },
}


class ProfileRepository:
    """
    Pure SQLModel repository replacing legacy JSON ground_truth_store.py.
    Stores all candidate profile, work history, education, skills, and FAQ data
    encrypted at rest inside the `candidate_profiles` SQL table.
    """

    def __init__(self, skills_md_path=SKILLS_MD_FILE):
        self.skills_md_path = skills_md_path
        init_db()

    def _ensure_seeded(self) -> CandidateProfile:
        with Session(engine) as session:
            profiles = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).all()
            for prof in profiles:
                owner = str((prof.parsed_skills or {}).get("owner_email") or "").strip().lower()
                if not owner and prof.full_name:
                    return prof
            if profiles and profiles[0].full_name:
                return profiles[0]

        from ..services.profile_service import profile_service
        raw_md = ""
        if self.skills_md_path.exists():
            raw_md = self.skills_md_path.read_text(encoding="utf-8")
        return profile_service.upsert_candidate_profile(raw_md, mark_uploaded=False)

    def get_profile_record(
        self,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> CandidateProfile:
        from .models import User

        target = owner_email.strip().lower() if owner_email else ""
        is_explicit_user = bool(
            (target and target != "guest@talentflow.local")
            or (user_id is not None)
        )
        if is_explicit_user:
            with Session(engine, expire_on_commit=False) as session:
                resolved_uid = user_id
                if resolved_uid is None and target:
                    u_row = session.exec(select(User).where(User.email == target)).first()
                    if u_row:
                        resolved_uid = u_row.id
                        if u_row.email == "guest@talentflow.local" and not target:
                            is_explicit_user = False

                if resolved_uid is not None:
                    prof_by_uid = session.exec(
                        select(CandidateProfile)
                        .where(CandidateProfile.user_id == resolved_uid)
                        .order_by(CandidateProfile.updated_at.desc())
                    ).first()
                    if prof_by_uid:
                        return prof_by_uid

                if target and target != "guest@talentflow.local":
                    profiles = session.exec(
                        select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
                    ).all()
                    for prof in profiles:
                        if str((prof.parsed_skills or {}).get("owner_email") or "").strip().lower() == target:
                            if resolved_uid is not None and prof.user_id is None:
                                prof.user_id = resolved_uid
                                session.add(prof)
                                session.commit()
                                session.refresh(prof)
                            return prof

                    # Authenticated user has no uploaded profile yet -> return an isolated blank profile for this user
                    # (never leak another user's CandidateProfile!)
                    blank_profile = CandidateProfile(
                        user_id=resolved_uid,
                        full_name="",
                        email=target,
                        raw_markdown="",
                        parsed_skills={
                            "user_uploaded": False,
                            "owner_email": target,
                            "user_id": resolved_uid,
                            "all_skills": [],
                            "ground_truth_vault": {
                                "candidate": {"full_name": "", "email": target},
                                "skills": {"core": [], "secondary": []},
                                "work_history": [],
                                "education": [],
                            },
                        },
                        experience_years=0.0,
                    )
                    session.add(blank_profile)
                    session.commit()
                    session.refresh(blank_profile)
                    return blank_profile

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
        city = loc.get("city", "") if isinstance(loc, dict) else ""
        base_note = f"Based in {city}; " if city else ""
        return [
            {
                "question_trigger": "notice period / earliest start date",
                "tags": ["availability", "notice", "start_date"],
                "answer": "Available to start 1 week after offer acceptance.",
            },
            {
                "question_trigger": "work authorization / remote B2B & visa status",
                "tags": ["visa", "b2b", "remote", "authorization"],
                "answer": f"{base_note}Available for local employment or international remote B2B engagements.",
            },
        ]

    def _normalize_vault(self, vault: Dict[str, Any], profile: CandidateProfile) -> Dict[str, Any]:
        """Normalizes vault fields without hardcoding citizenship, visa assumptions, or fake salary targets."""
        data = dict(vault or {})
        raw_md = profile.raw_markdown or ""
        parsed_md = self.parse_profile_from_md(raw_md) if raw_md else {}
        ps = dict(profile.parsed_skills or {})

        cand = dict(data.get("candidate") or {})
        full_name = cand.get("full_name") or profile.full_name or "Candidate"
        parts = full_name.split()
        cand.setdefault("first_name", parts[0] if parts else "")
        cand.setdefault("last_name", " ".join(parts[1:]) if len(parts) > 1 else "")
        cand["full_name"] = full_name
        cand.setdefault("headline", ps.get("headline") or parsed_md.get("headline") or "")
        cand.setdefault("email", profile.email if profile.email != "candidate@example.com" else "")
        cand.setdefault("phone", profile.phone if "+000" not in str(profile.phone or "") else "")
        if not cand.get("phone") and parsed_md.get("phone"):
            cand["phone"] = parsed_md["phone"]

        loc = cand.get("location")
        if not isinstance(loc, dict):
            loc = {}
        raw_loc_str = (profile.location or parsed_md.get("location") or "").strip()
        if raw_loc_str and not loc.get("city"):
            loc_parts = [p.strip() for p in raw_loc_str.split(",", 1)]
            loc["city"] = loc_parts[0]
            if len(loc_parts) > 1 and not loc.get("country"):
                loc["country"] = loc_parts[1]
        loc.setdefault("city", "")
        loc.setdefault("country", "")
        loc.setdefault("timezone", "")
        loc.setdefault("open_to_relocation", False)
        loc.setdefault("remote_preference", "")
        cand["location"] = loc

        links = cand.get("links")
        if not isinstance(links, dict):
            links = {}
        links.setdefault("linkedin", "" if "example-candidate" in str(profile.linkedin_url or "") else (profile.linkedin_url or ""))
        links.setdefault("github", "" if "example-candidate" in str(profile.github_url or "") else (profile.github_url or ""))
        links.setdefault("portfolio", "")
        cand["links"] = links

        # Neutral empty defaults for citizenship & visas until explicitly populated by user
        wa = cand.get("work_authorization")
        if not isinstance(wa, dict):
            wa = {}
        wa.setdefault("citizenship", [])
        wa.setdefault("eu_work_permit", False)
        wa.setdefault("requires_eu_visa", False)
        wa.setdefault("us_work_authorization", "")
        wa.setdefault("requires_us_visa_sponsorship", False)
        wa.setdefault("uk_work_authorization", "")
        wa.setdefault("security_clearance", False)
        cand["work_authorization"] = wa

        comp = cand.get("compensation")
        if not isinstance(comp, dict):
            comp = {}
        comp.setdefault("expected_salary_eur", 0)
        comp.setdefault("min_salary_eur", 0)
        comp.setdefault("expected_salary_usd", 0)
        comp.setdefault("notice_period", "")
        cand["compensation"] = comp

        langs = cand.get("languages")
        if not isinstance(langs, list) or not langs:
            spoken = ps.get("spoken_languages") or []
            langs = [{"language": str(l), "proficiency": ""} for l in spoken]
        cand["languages"] = langs
        data["candidate"] = cand

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
        if not isinstance(edu, list) or not edu:
            edu = ps.get("education") or parsed_md.get("education") or []
        data["education"] = edu

        faq = data.get("faq_bank")
        if not isinstance(faq, list) or not faq:
            faq = self._default_faq_bank(cand)
        data["faq_bank"] = faq

        data.setdefault("cv_variants", {})
        data["skills_md_raw"] = raw_md
        data["parsed_skills_taxonomy"] = {k: v for k, v in ps.items() if k != "ground_truth_vault"}
        return data

    def get_data(
        self,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        profile = self.get_profile_record(owner_email=owner_email, user_id=user_id)
        raw_vault = dict((profile.parsed_skills or {}).get("ground_truth_vault") or {})
        return self._normalize_vault(raw_vault, profile)

    def update_data(
        self,
        data: Dict[str, Any],
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        save_copy = dict(data)
        raw_md = save_copy.pop("skills_md_raw", None)
        save_copy.pop("parsed_skills_taxonomy", None)

        target_prof = self.get_profile_record(owner_email=owner_email, user_id=user_id)

        with Session(engine) as session:
            profile = session.get(CandidateProfile, target_prof.id) if target_prof and target_prof.id else None
            if not profile:
                profile = self._ensure_seeded()
                profile = session.get(CandidateProfile, profile.id)

            if user_id is not None and profile.user_id is None:
                profile.user_id = user_id

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
            if isinstance(save_copy.get("skills"), dict) and isinstance(save_copy["skills"].get("core"), list):
                cleaned_core = dedupe_skills_case_insensitive([str(x) for x in save_copy["skills"]["core"]])
                save_copy["skills"]["core"] = cleaned_core
                taxonomy["all_skills"] = cleaned_core
            for preserve_key in ("user_uploaded", "owner_email", "user_id", "education", "courses_and_certifications", "eligible_internships"):
                if preserve_key in existing_ps:
                    taxonomy[preserve_key] = existing_ps[preserve_key]
            if owner_email and owner_email != "guest@talentflow.local":
                taxonomy["owner_email"] = owner_email.strip().lower()
            if user_id is not None:
                taxonomy["user_id"] = user_id
            taxonomy["ground_truth_vault"] = save_copy
            profile.parsed_skills = taxonomy
            profile.updated_at = utc_now()
            session.add(profile)
            session.commit()

        return self.get_data(owner_email=owner_email, user_id=user_id)

    def get_skills_md(
        self,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> str:
        profile = self.get_profile_record(owner_email=owner_email, user_id=user_id)
        return profile.raw_markdown or ""

    def parse_profile_from_md(self, md_content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        lines = md_content.splitlines()
        header_block = "\n".join(lines[:15])

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
        if not phone_m:
            phone_m = re.search(
                r"(?<!\d)(\+\d{1,3}[\s.-]?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4})(?!\d)",
                header_block,
            )
        if phone_m:
            result["phone"] = phone_m.group(1).strip(" -\t\r\n")

        loc_m = re.search(r"(?:Location|მდებარეობა)\**\s*:\**\s*([^\n]+)", md_content, re.I)
        if not loc_m:
            loc_m = re.search(
                r"(?:^|[•|])\s*([A-Z][A-Za-zÀ-ÿ .-]{1,28},\s*[A-Z][A-Za-zÀ-ÿ .-]{1,28})\s*(?:$|[•|])",
                header_block,
                re.M,
            )
        if loc_m:
            result["location"] = loc_m.group(1).strip()

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
        education_items = []
        in_exp = False
        in_edu = False
        current_job = None
        for line in lines:
            s = line.strip()
            if s.startswith("## ") and not s.startswith("### "):
                low_h = s.lower()
                in_exp = any(w in low_h for w in ["experience", "history", "work", "გამოცდილება", "სამუშაო"])
                in_edu = any(w in low_h for w in ["education", "academic", "university", "განათლება", "სწავლა"])
                if not in_exp and current_job:
                    work_history.append(current_job)
                    current_job = None
                continue
            if in_exp:
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
                        "location": "",
                        "start_date": "",
                        "end_date": "Present",
                        "highlights": [],
                    }
                elif current_job and (
                    (s.startswith(("*", "-")) and not s.startswith("* ") and s.endswith("*"))
                    or (
                        re.search(r"(?:20\d{2}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|present)", s, re.I)
                        and len(s) < 90
                        and ("•" in s or ("*" in s and ("–" in s or "-" in s)))
                    )
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
            elif in_edu and s and not s.startswith("#"):
                clean_e = re.sub(r"^[-*]\s*", "", s)
                clean_e = re.sub(r"[*_`]+", "", clean_e).strip()
                if clean_e and not re.fullmatch(r"[-*_•–—.\s]+", clean_e):
                    yr_m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", clean_e)
                    education_items.append({
                        "degree": clean_e.split("|")[0].split("—")[0].strip(),
                        "institution": clean_e.split("|")[1].strip() if "|" in clean_e else clean_e,
                        "graduation_year": int(yr_m.group(1)) if yr_m else None,
                        "focus": clean_e,
                    })

        if current_job:
            work_history.append(current_job)
        if work_history:
            result["work_history"] = work_history
        if education_items:
            result["education"] = education_items

        return result

    def ingest_skills_markdown(
        self,
        md_content: str,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> CandidateProfile:
        from sqlmodel import delete
        from .models import CandidateExperience
        from ..services.profile_service import profile_service
        profile = profile_service.upsert_candidate_profile(
            md_content, mark_uploaded=True, owner_email=owner_email, user_id=user_id
        )
        parsed = self.parse_profile_from_md(md_content)
        if parsed.get("work_history") or parsed.get("education"):
            with Session(engine, expire_on_commit=False) as session:
                db_prof = session.get(CandidateProfile, profile.id)
                if db_prof:
                    skills_copy = dict(db_prof.parsed_skills)
                    vault = dict(skills_copy.get("ground_truth_vault") or {})
                    if parsed.get("work_history"):
                        vault["work_history"] = parsed["work_history"]
                        if db_prof.id is not None:
                            session.exec(delete(CandidateExperience).where(CandidateExperience.profile_id == db_prof.id))
                            for wh_item in parsed["work_history"]:
                                if isinstance(wh_item, dict):
                                    session.add(
                                        CandidateExperience(
                                            profile_id=db_prof.id,
                                            user_id=db_prof.user_id,
                                            company=str(wh_item.get("company") or "Experience"),
                                            role_title=str(wh_item.get("role") or wh_item.get("title") or "Role"),
                                            location=str(wh_item.get("location") or ""),
                                            start_date=str(wh_item.get("dates") or wh_item.get("start_date") or ""),
                                            highlights=list(wh_item.get("highlights") or []),
                                        )
                                    )
                    if parsed.get("education"):
                        vault["education"] = parsed["education"]
                    skills_copy["ground_truth_vault"] = vault
                    db_prof.parsed_skills = skills_copy
                    session.add(db_prof)
                    session.commit()
                    session.refresh(db_prof)
                    return db_prof
        return profile

    def save_skills_md(
        self,
        md_content: str,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.ingest_skills_markdown(md_content, owner_email=owner_email, user_id=user_id)
        return self.get_data(owner_email=owner_email, user_id=user_id)

    def extract_skills_from_md(self, md_content: str) -> List[str]:
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


profile_repository = ProfileRepository()
ground_truth_store = profile_repository
