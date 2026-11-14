import logging
import re
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ..config import SKILLS_MD_FILE
from .database import engine, init_db
from .models import CandidateProfile, utc_now
from ..services.matcher_service import matcher_service, dedupe_skills_case_insensitive

logger = logging.getLogger(__name__)

_PROGRAMMING_LANG_NOISE = {
    "typescript", "javascript", "python", "sql", "html", "html5", "css", "css3",
    "java", "c#", "c++", "go", "golang", "rust", "php", "ruby", "bash", "shell",
    "kotlin", "swift", "scala", "dom", "dom tree", "css selectors", "xpath",
    "xpath locators", "json", "xml", "yaml", "graphql", "postgresql", "mysql",
}

_KNOWN_SPOKEN_LANGUAGES = {
    "english", "georgian", "german", "french", "spanish", "italian", "russian",
    "ukrainian", "polish", "portuguese", "dutch", "turkish", "arabic", "chinese",
    "japanese", "korean", "hindi", "armenian", "azerbaijani", "hebrew", "greek",
    "ქართული", "ინგლისური", "გერმანული", "რუსული", "ფრანგული", "ესპანური", "თურქული",
}


def is_programming_token(raw: str) -> bool:
    s = re.sub(r"[*_`()\[\]:]+", " ", str(raw or "")).strip().lower()
    if not s:
        return True
    if any(tok in s for tok in (
        "typescript", "javascript", "python", "html5", "css3", "xpath", "dom tree",
        "css selectors", "locators", "sql", "selenium", "playwright", "pytest",
    )):
        return True
    first_word = re.split(r"[\s:/(,]+", s)[0]
    return first_word in _PROGRAMMING_LANG_NOISE


def filter_spoken_language_entries(items: List[Any]) -> List[Dict[str, str]]:
    """Keeps strictly human spoken languages (rejecting TypeScript/Python/SQL/CSS/XPath)."""
    result: List[Dict[str, str]] = []
    seen = set()
    for item in (items or []):
        if isinstance(item, dict):
            lang = str(item.get("language") or item.get("name") or "").strip()
            prof = str(item.get("proficiency") or item.get("level") or "").strip()
        else:
            raw = str(item or "").strip()
            if not raw:
                continue
            if ":" in raw:
                lang, prof = [x.strip() for x in raw.split(":", 1)]
            elif "(" in raw and raw.endswith(")"):
                idx = raw.find("(")
                lang = raw[:idx].strip()
                prof = raw[idx + 1:-1].strip()
            else:
                lang, prof = raw, ""
        lang = re.sub(r"[*_`]+", "", lang).strip(" :-–—•")
        prof = re.sub(r"[*_`]+", "", prof).strip()
        if not lang or is_programming_token(lang) or is_programming_token(f"{lang} {prof}"):
            continue
        low = lang.lower()
        # Require either known spoken language or not obviously code/tooling
        if low in seen:
            continue
        if any(k in low for k in _KNOWN_SPOKEN_LANGUAGES) or (len(lang.split()) <= 3 and not any(ch in lang for ch in "/+.#")):
            seen.add(low)
            result.append({"language": lang, "proficiency": prof})
    return result

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
                ps = prof.parsed_skills or {}
                owner = str(ps.get("owner_email") or "").strip().lower()
                if not owner and prof.user_id is None and (prof.full_name or prof.raw_markdown) and bool(ps.get("user_uploaded", False)):
                    return prof
            for prof in profiles:
                ps = prof.parsed_skills or {}
                owner = str(ps.get("owner_email") or "").strip().lower()
                if not owner and prof.user_id is None and (prof.full_name or prof.raw_markdown):
                    return prof

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
        if target == "guest@talentflow.local":
            target = ""

        with Session(engine, expire_on_commit=False) as session:
            resolved_uid = user_id
            if resolved_uid is not None and not target:
                u_row = session.get(User, resolved_uid)
                if u_row:
                    if (u_row.email or "").strip().lower() == "guest@talentflow.local":
                        resolved_uid = None
                    else:
                        target = (u_row.email or "").strip().lower()
            elif resolved_uid is None and target:
                u_row = session.exec(select(User).where(User.email == target)).first()
                if u_row:
                    if (u_row.email or "").strip().lower() == "guest@talentflow.local":
                        target = ""
                    else:
                        resolved_uid = u_row.id

            is_explicit_user = bool(target or (resolved_uid is not None))
            if is_explicit_user:
                if resolved_uid is not None:
                    prof_by_uid = session.exec(
                        select(CandidateProfile)
                        .where(CandidateProfile.user_id == resolved_uid)
                        .order_by(CandidateProfile.updated_at.desc())
                    ).first()
                    if prof_by_uid and (prof_by_uid.full_name or prof_by_uid.raw_markdown):
                        return prof_by_uid

                if target:
                    profiles = session.exec(
                        select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
                    ).all()
                    for prof in profiles:
                        if str((prof.parsed_skills or {}).get("owner_email") or "").strip().lower() == target:
                            if prof.full_name or prof.raw_markdown:
                                if resolved_uid is not None and prof.user_id is None:
                                    prof.user_id = resolved_uid
                                    session.add(prof)
                                    session.commit()
                                    session.refresh(prof)
                                return prof

                    # Authenticated user has no uploaded profile yet -> return an in-memory blank profile
                    # (never persist blank rows to DB and never leak another user's CandidateProfile!)
                    return CandidateProfile(
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

        raw_langs = cand.get("languages")
        if not isinstance(raw_langs, list) or not raw_langs:
            spoken = parsed_md.get("spoken_languages") or ps.get("spoken_languages") or []
            raw_langs = spoken
        filtered_langs = filter_spoken_language_entries(raw_langs)
        if not filtered_langs and parsed_md.get("spoken_languages"):
            filtered_langs = filter_spoken_language_entries(parsed_md["spoken_languages"])
        cand["languages"] = filtered_langs
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
        parsed_edu = parsed_md.get("education") or []
        is_fragmented_edu = (
            isinstance(edu, list)
            and bool(edu)
            and all(
                isinstance(e, dict)
                and (
                    not e.get("institution")
                    or e.get("institution") == e.get("degree")
                    or e.get("degree") == e.get("focus")
                    or any(bad in str(e.get("degree") or "") for bad in ("Concentration:", "Academic Standing:", "Core Analytical Modules:", "Selected for Erasmus"))
                )
                for e in edu
            )
        )
        if is_fragmented_edu or not isinstance(edu, list) or not edu:
            edu = parsed_edu or ps.get("education") or []
        data["education"] = edu

        if parsed_md.get("projects"):
            data["projects"] = parsed_md["projects"]
        else:
            data.setdefault("projects", [])
        if parsed_md.get("certifications"):
            data["certifications"] = parsed_md["certifications"]
        elif ps.get("courses_and_certifications"):
            data["certifications"] = ps.get("courses_and_certifications") or []
        else:
            data.setdefault("certifications", [])

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
        projects_list = []
        education_items = []
        certifications_list = []
        spoken_langs = []
        in_exp = False
        in_proj = False
        in_edu = False
        in_cert = False
        in_lang = False
        current_job = None
        current_proj = None
        current_edu = None

        def _flush_edu() -> None:
            nonlocal current_edu
            if current_edu:
                mods = [m for m in (current_edu.get("modules") or []) if m]
                if mods and not current_edu.get("field_of_study"):
                    current_edu["field_of_study"] = ", ".join(mods)
                if current_edu.get("field_of_study"):
                    current_edu["focus"] = current_edu["field_of_study"]
                education_items.append(current_edu)
                current_edu = None

        def _flush_proj() -> None:
            nonlocal current_proj
            if current_proj:
                projects_list.append(current_proj)
                current_proj = None

        for line in lines:
            s = line.strip()
            if s.startswith("## ") and not s.startswith("### "):
                low_h = s.lower()
                in_exp = any(w in low_h for w in ["experience", "history", "work", "გამოცდილება", "სამუშაო"])
                in_proj = any(w in low_h for w in ["project", "portfolio", "პროექტ"])
                in_edu = any(w in low_h for w in ["education", "academic", "university", "განათლება", "სწავლა"])
                in_cert = any(w in low_h for w in ["training", "certif", "course", "bootcamp", "სერტიფიკატ", "კურს"])
                in_lang = any(w in low_h for w in ["language", "spoken", "ენებ"]) and "skill" not in low_h
                if not in_exp and current_job:
                    work_history.append(current_job)
                    current_job = None
                if not in_proj:
                    _flush_proj()
                if not in_edu:
                    _flush_edu()
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

            elif in_proj:
                if re.fullmatch(r"[-*_=\s]{2,}", s):
                    continue
                if s.startswith("### "):
                    _flush_proj()
                    current_proj = {
                        "title": re.sub(r"[*_`]+", "", s[4:]).strip(),
                        "organization": "",
                        "dates": "",
                        "highlights": [],
                    }
                elif current_proj and s.startswith("**") and not s.startswith("* "):
                    meta = re.sub(r"[*_`]+", "", s).strip()
                    if "•" in meta:
                        org_p, dt_p = [x.strip() for x in meta.split("•", 1)]
                        current_proj["organization"] = re.sub(r"^role\s*:\s*", "", org_p, flags=re.I)
                        current_proj["dates"] = dt_p
                    else:
                        current_proj["organization"] = re.sub(r"^role\s*:\s*", "", meta, flags=re.I)
                elif current_proj and s.startswith(("-", "*")):
                    bullet = re.sub(r"^[-*]\s*", "", s).strip()
                    bullet = re.sub(r"[*_`]+", "", bullet).strip()
                    if bullet and not re.fullmatch(r"[-*_•–—.\s]+", bullet):
                        current_proj["highlights"].append(bullet)

            elif in_edu:
                if re.fullmatch(r"[-*_=\s]{2,}", s) or not s:
                    continue
                if s.startswith("### "):
                    _flush_edu()
                    deg_header = re.sub(r"[*_`]+", "", s[4:]).strip()
                    deg_parts = [p.strip() for p in re.split(r"\s+[|•—]\s+", deg_header, maxsplit=1)]
                    current_edu = {
                        "degree": deg_parts[0],
                        "institution": deg_parts[1] if len(deg_parts) > 1 else "",
                        "location": "",
                        "dates": "",
                        "start_year": None,
                        "end_year": None,
                        "graduation_year": None,
                        "gpa": "",
                        "modules": [],
                        "field_of_study": "",
                        "focus": "",
                        "is_student_or_recent_grad": bool(re.search(r"present|202[4-9]|student|msc|bsc", deg_header, re.I)),
                    }
                elif current_edu is not None:
                    clean_e = re.sub(r"^[-*]\s*", "", s)
                    clean_e = re.sub(r"[*_`]+", "", clean_e).strip()
                    if not clean_e or re.fullmatch(r"[-*_•–—.\s]+", clean_e):
                        continue
                    # Institution line e.g. "**Ivane Javakhishvili Tbilisi State University (TSU)** • *Tbilisi, Georgia*"
                    if s.startswith("**") and not s.startswith("* "):
                        if "•" in clean_e:
                            inst_p, loc_p = [x.strip() for x in clean_e.split("•", 1)]
                            current_edu["institution"] = inst_p
                            current_edu["location"] = loc_p
                        else:
                            current_edu["institution"] = clean_e
                    # Italic date range line e.g. "*2026 – Present*" or "*2022 – 2026*"
                    elif (s.startswith("*") and s.endswith("*") and not s.startswith("* ")) or (
                        re.match(r"^(?:19\d{2}|20\d{2})\s*[–-]\s*(?:19\d{2}|20\d{2}|present|current)$", clean_e, re.I)
                    ):
                        current_edu["dates"] = clean_e
                        yrs = [int(y) for y in re.findall(r"\b(19\d{2}|20[0-3]\d)\b", clean_e)]
                        if yrs:
                            current_edu["start_year"] = yrs[0]
                            if "present" in clean_e.lower() or "current" in clean_e.lower():
                                current_edu["end_year"] = None
                                current_edu["graduation_year"] = yrs[0]
                                current_edu["is_student_or_recent_grad"] = True
                            else:
                                current_edu["end_year"] = yrs[-1]
                                current_edu["graduation_year"] = yrs[-1]
                                if yrs[-1] >= 2022:
                                    current_edu["is_student_or_recent_grad"] = True
                    # Bullets inside the degree block: GPA, Studying Subjects / Core Modules / Concentration
                    else:
                        gpa_m = re.search(r"gpa\s*:?\s*(\d(?:\.\d+)?\s*/\s*\d(?:\.\d+)?)", clean_e, re.I)
                        if gpa_m:
                            current_edu["gpa"] = gpa_m.group(1).strip()
                        mod_m = re.match(
                            r"^(?:studying\s+subjects\s*/\s*core\s+modules|studying\s+subjects|core\s+analytical\s+modules|core\s+modules|modules|subjects|coursework|concentration|academic\s+standing|საგნები|მოდულები)\s*:\s*(.+)$",
                            clean_e,
                            re.I,
                        )
                        if mod_m:
                            lbl = clean_e.split(":", 1)[0].strip().lower()
                            val = mod_m.group(1).strip().rstrip(".")
                            if "academic standing" in lbl:
                                if not current_edu["gpa"] and gpa_m:
                                    current_edu["gpa"] = gpa_m.group(1).strip()
                            else:
                                split_mods = [
                                    m.strip()
                                    for m in re.split(r"\s*[,;/]\s*", val)
                                    if m.strip()
                                ]
                                current_edu["modules"].extend(
                                    m for m in split_mods if m not in current_edu["modules"]
                                )
                                current_edu["field_of_study"] = (
                                    f"{current_edu['field_of_study']}; {val}".strip("; ")
                                    if current_edu["field_of_study"]
                                    else val
                                )
                        else:
                            current_edu["modules"].append(clean_e.rstrip("."))
                else:
                    # Fallback for bullet-only Education sections without ### subheadings
                    clean_e = re.sub(r"^[-*]\s*", "", s)
                    clean_e = re.sub(r"[*_`]+", "", clean_e).strip()
                    if clean_e and not re.fullmatch(r"[-*_•–—.\s]+", clean_e):
                        yr_m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", clean_e)
                        parts_e = [p.strip() for p in re.split(r"\s*[|—]\s*", clean_e) if p.strip()]
                        deg_txt = parts_e[0] if parts_e else clean_e
                        inst_txt = parts_e[1] if len(parts_e) > 1 else ""
                        education_items.append({
                            "degree": deg_txt,
                            "institution": inst_txt,
                            "location": "",
                            "dates": yr_m.group(1) if yr_m else "",
                            "graduation_year": int(yr_m.group(1)) if yr_m else None,
                            "gpa": "",
                            "modules": [],
                            "field_of_study": "",
                            "focus": "",
                            "is_student_or_recent_grad": bool(yr_m and int(yr_m.group(1)) >= 2022),
                        })

            elif in_cert:
                if re.fullmatch(r"[-*_=\s]{2,}", s) or not s or s.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                if s.startswith(("- ", "* ")) and indent == 0:
                    clean_c = re.sub(r"^[-*]\s+", "", s)
                    clean_c = re.sub(r"[*_`]+", "", clean_c).strip()
                    if clean_c:
                        certifications_list.append(clean_c)
                elif s.startswith(("- ", "* ")) and indent >= 2 and certifications_list:
                    detail = re.sub(r"^[-*]\s+", "", s)
                    detail = re.sub(r"[*_`]+", "", detail).strip()
                    if detail and not detail.startswith(certifications_list[-1]):
                        certifications_list[-1] = f"{certifications_list[-1]}: {detail}"
                elif certifications_list and indent >= 2:
                    detail = re.sub(r"[*_`]+", "", s).strip()
                    if detail:
                        certifications_list[-1] = f"{certifications_list[-1]} — {detail}"

            elif in_lang:
                if re.fullmatch(r"[-*_=\s]{2,}", s) or not s or s.startswith("#"):
                    continue
                clean_l = re.sub(r"^[-*]\s*", "", s)
                clean_l = re.sub(r"[*_`]+", "", clean_l).strip()
                if clean_l:
                    spoken_langs.extend(filter_spoken_language_entries([clean_l]))

        if current_job:
            work_history.append(current_job)
        _flush_proj()
        _flush_edu()

        if work_history:
            result["work_history"] = work_history
        if projects_list:
            result["projects"] = projects_list
        if education_items:
            result["education"] = education_items
        if certifications_list:
            result["certifications"] = certifications_list
        if spoken_langs:
            result["spoken_languages"] = spoken_langs

        return result

    def ingest_skills_markdown(
        self,
        md_content: str,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> CandidateProfile:
        from sqlmodel import delete
        from .models import CandidateExperience, CandidateEducation
        from ..services.profile_service import profile_service
        profile = profile_service.upsert_candidate_profile(
            md_content, mark_uploaded=True, owner_email=owner_email, user_id=user_id
        )
        parsed = self.parse_profile_from_md(md_content)
        with Session(engine, expire_on_commit=False) as session:
            db_prof = session.get(CandidateProfile, profile.id)
            if db_prof:
                skills_copy = dict(db_prof.parsed_skills or {})
                vault = dict(skills_copy.get("ground_truth_vault") or {})
                vault["work_history"] = list(parsed.get("work_history") or [])
                if parsed.get("projects"):
                    vault["projects"] = list(parsed["projects"])
                    skills_copy["projects"] = list(parsed["projects"])
                if parsed.get("certifications"):
                    vault["certifications"] = list(parsed["certifications"])
                    skills_copy["courses_and_certifications"] = list(parsed["certifications"])
                if parsed.get("spoken_languages"):
                    cand_v = dict(vault.get("candidate") or {})
                    cand_v["languages"] = list(parsed["spoken_languages"])
                    vault["candidate"] = cand_v
                    skills_copy["spoken_languages"] = [
                        f"{l['language']} ({l['proficiency']})" if l.get("proficiency") else l["language"]
                        for l in parsed["spoken_languages"]
                    ]
                if db_prof.id is not None:
                    session.exec(delete(CandidateExperience).where(CandidateExperience.profile_id == db_prof.id))
                    for wh_item in vault["work_history"]:
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
                grouped_edu = list(parsed.get("education") or vault.get("education") or [])
                vault["education"] = grouped_edu
                skills_copy["education"] = grouped_edu
                if db_prof.id is not None and grouped_edu:
                    session.exec(delete(CandidateEducation).where(CandidateEducation.profile_id == db_prof.id))
                    for edu_item in grouped_edu:
                        if isinstance(edu_item, dict):
                            session.add(
                                CandidateEducation(
                                    profile_id=db_prof.id,
                                    user_id=db_prof.user_id,
                                    institution=str(edu_item.get("institution") or "")[:120],
                                    degree=str(edu_item.get("degree") or "")[:200],
                                    field_of_study=str(edu_item.get("field_of_study") or edu_item.get("focus") or "")[:250],
                                    graduation_year=str(edu_item.get("dates") or edu_item.get("graduation_year") or "")[:32],
                                    coursework=list(edu_item.get("modules") or []),
                                )
                            )
                skills_copy["ground_truth_vault"] = vault
                db_prof.parsed_skills = skills_copy
                session.add(db_prof)
                session.commit()
                session.refresh(db_prof)
                profile = db_prof
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
