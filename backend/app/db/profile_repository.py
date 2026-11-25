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


_AI_META_PROSE_RE = re.compile(
    r"^(?:#\s*\d+\.|treat\s+the\b|potential\s+transferable\b|these\s+strengths\b|"
    r"do\s+not\s+claim\b|use\s+these\s+as\b|ignore\s+any\b|you\s+are\s+an?\b|"
    r"act\s+as\s+an?\b|never\s+fabricate\b|instructions?\s*:|system\s+prompt)",
    re.I,
)

_INVALID_PERSON_NAME_RE = re.compile(
    r"(?:interview[\s_-]?coach|career[\s_-]?intelligence|assistant|prompt|readme|case\s+study|"
    r"portfolio|documentation|guide|verified\s+work|skills\.md|http://|https://|@)",
    re.I,
)


def strip_yaml_frontmatter(md_content: str) -> str:
    """Removes leading YAML frontmatter (`--- ... ---`) so AI skill metadata never leaks into CV fields."""
    if not md_content:
        return ""
    return re.sub(r"\A\ufeff?---\s*\r?\n[\s\S]*?\r?\n---\s*(?:\r?\n|$)", "", md_content)


def sanitize_person_name(raw_name: str) -> str:
    """Cleans markdown formatting and rejects AI skill slugs / prompt titles as candidate names."""
    cleaned = re.sub(r"[*_`#]+", "", str(raw_name or "")).strip(" :-–—•|")
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 80:
        return ""
    # Reject hyphenated slug identifiers such as `giorgi-career-intelligence-interview-coach`
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", cleaned):
        return ""
    if _INVALID_PERSON_NAME_RE.search(cleaned):
        return ""
    return cleaned


def is_corrupted_education_entry(entry: Any) -> bool:
    """Detects AI meta-prompt lines or orphan date/skill fragments accidentally stored as Education."""
    if isinstance(entry, dict):
        deg = str(entry.get("degree") or "").strip()
        inst = str(entry.get("institution") or "").strip()
        txt = f"{deg} {inst}".strip()
    else:
        txt = str(entry or "").strip()
        deg = txt
        inst = ""
    if not txt:
        return True
    if _AI_META_PROSE_RE.search(txt) or deg.startswith("#"):
        return True
    if re.fullmatch(r"(?:19|20)\d{2}(?:\s*[–\-]\s*(?:(?:19|20)\d{2}|present|current))?", deg, re.I) and not inst:
        return True
    if deg.lower() in (
        "graduated with honors", "honors", "banking", "fintech", "payments", "financial products",
        "operations", "risk", "analytics", "data-intensive systems", "business-oriented software testing",
        "analytical reasoning", "quantitative thinking", "business logic", "financial-domain understanding",
        "data interpretation", "data validation", "process analysis", "risk-oriented thinking",
        "understanding of business requirements",
    ):
        return True
    return False


def filter_spoken_language_entries(items: List[Any]) -> List[Dict[str, str]]:
    """Keeps strictly human spoken languages (rejecting TypeScript/Python/SQL/CSS/XPath)."""
    result: List[Dict[str, str]] = []
    seen = set()
    expanded: List[Any] = []
    for item in (items or []):
        if isinstance(item, dict):
            lang_v = str(item.get("language") or item.get("name") or "").strip()
            prof_v = str(item.get("proficiency") or item.get("level") or "").strip()
            if "|" in prof_v and ":" in prof_v:
                expanded.extend(p.strip() for p in f"{lang_v}: {prof_v}".split("|") if p.strip())
            else:
                expanded.append(item)
        else:
            raw_s = str(item or "").strip()
            if "|" in raw_s or "•" in raw_s:
                expanded.extend(p.strip() for p in re.split(r"[|•]", raw_s) if p.strip())
            else:
                expanded.append(raw_s)
    for item in expanded:
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
        if self.skills_md_path.exists():
            raw_md = self.skills_md_path.read_text(encoding="utf-8")
            return profile_service.upsert_candidate_profile(raw_md, mark_uploaded=False)

        with Session(engine, expire_on_commit=False) as session:
            blank = CandidateProfile(
                user_id=None,
                full_name="",
                email="",
                raw_markdown="",
                parsed_skills={
                    "user_uploaded": False,
                    "experience_status": "unknown",
                    "all_skills": [],
                    "ground_truth_vault": {
                        "candidate": {"full_name": "", "email": ""},
                        "skills": {"core": [], "secondary": []},
                        "work_history": [],
                        "education": [],
                    },
                },
                experience_years=None,
            )
            session.add(blank)
            session.commit()
            session.refresh(blank)
            return blank

    def get_profile_record(
        self,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> CandidateProfile:
        from .models import User
        from ..services.auth_service import get_user_by_email

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
                u_row = get_user_by_email(session, target)
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
                        experience_years=None,
                    )

        return self._ensure_seeded()

    def get_preset_md(self, preset_id: str) -> str:
        preset = PROFESSION_MD_PRESETS.get(preset_id)
        if not preset:
            raise ValueError(f"Unknown preset_id: {preset_id}")
        return preset["content"]

    @staticmethod
    def sync_relational_children(
        session: Session,
        profile: CandidateProfile,
        *,
        skills_payload: Optional[Dict[str, Any]] = None,
        work_history: Optional[List[Any]] = None,
        education_entries: Optional[List[Any]] = None,
        fallback_role: str = "Role",
    ) -> None:
        """Single authoritative sync for CandidateSkill, CandidateExperience, and CandidateEducation rows."""
        if profile.id is None:
            return
        from sqlmodel import delete
        from .models import CandidateSkill, CandidateExperience, CandidateEducation

        if skills_payload is not None:
            session.exec(delete(CandidateSkill).where(CandidateSkill.profile_id == profile.id))
            seen_skills: set[str] = set()
            for cat_name, items in [
                ("qa_automation", skills_payload.get("qa_automation", [])),
                ("manual_qa", skills_payload.get("manual_qa", [])),
                ("languages", skills_payload.get("languages", [])),
                ("api_and_performance", skills_payload.get("api_and_performance", [])),
                ("cicd_and_devops", skills_payload.get("cicd_and_devops", [])),
                ("tools", skills_payload.get("tools", [])),
                ("frameworks", skills_payload.get("frameworks", [])),
                ("general", skills_payload.get("all_skills", [])),
            ]:
                for sk in (items or []):
                    sk_clean = str(sk).strip()
                    if not sk_clean or sk_clean.lower() in seen_skills:
                        continue
                    seen_skills.add(sk_clean.lower())
                    session.add(
                        CandidateSkill(
                            profile_id=profile.id,
                            user_id=profile.user_id,
                            skill_name=sk_clean,
                            category=cat_name,
                            is_verified=True,
                        )
                    )

        if work_history is not None:
            session.exec(delete(CandidateExperience).where(CandidateExperience.profile_id == profile.id))
            if work_history:
                for wh_item in work_history:
                    if isinstance(wh_item, dict):
                        session.add(
                            CandidateExperience(
                                profile_id=profile.id,
                                user_id=profile.user_id,
                                company=str(wh_item.get("company") or "Experience"),
                                role_title=str(wh_item.get("role") or wh_item.get("title") or fallback_role),
                                location=str(wh_item.get("location") or ""),
                                start_date=str(wh_item.get("dates") or wh_item.get("start_date") or ""),
                                highlights=list(wh_item.get("highlights") or wh_item.get("bullets") or []),
                            )
                        )
            elif skills_payload and skills_payload.get("achievements"):
                session.add(
                    CandidateExperience(
                        profile_id=profile.id,
                        user_id=profile.user_id,
                        company="Professional Experience",
                        role_title=str(fallback_role or "Specialist"),
                        highlights=list(skills_payload.get("achievements", [])[:10]),
                    )
                )

        if education_entries is not None:
            session.exec(delete(CandidateEducation).where(CandidateEducation.profile_id == profile.id))
            for edu_item in education_entries:
                if isinstance(edu_item, dict):
                    inst = str(edu_item.get("institution") or edu_item.get("school") or "").strip()
                    deg = str(edu_item.get("degree") or edu_item.get("field") or inst).strip()
                    if not (inst or deg):
                        continue
                    session.add(
                        CandidateEducation(
                            profile_id=profile.id,
                            user_id=profile.user_id,
                            institution=(inst or deg)[:120],
                            degree=deg[:200],
                            field_of_study=str(edu_item.get("field_of_study") or edu_item.get("focus") or "")[:250] or None,
                            graduation_year=str(edu_item.get("dates") or edu_item.get("years") or edu_item.get("graduation_year") or "")[:32],
                            coursework=[str(m).strip() for m in (edu_item.get("modules") or []) if str(m).strip()],
                        )
                    )
                else:
                    edu_str = str(edu_item).strip()
                    if edu_str:
                        session.add(
                            CandidateEducation(
                                profile_id=profile.id,
                                user_id=profile.user_id,
                                institution=edu_str[:120],
                                degree=edu_str[:200],
                            )
                        )

    def _default_faq_bank(self, cand: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        comp = cand.get("compensation") if isinstance(cand.get("compensation"), dict) else {}
        notice = str(comp.get("notice_period") or "").strip()
        if notice:
            items.append(
                {
                    "question_trigger": "notice period / earliest start date",
                    "tags": ["availability", "notice", "start_date"],
                    "answer": notice,
                }
            )
        wa = cand.get("work_authorization") if isinstance(cand.get("work_authorization"), dict) else {}
        citizenships = [str(c).strip() for c in (wa.get("citizenship") or []) if str(c).strip()]
        if citizenships or wa.get("eu_work_permit") or wa.get("us_work_authorization") or wa.get("uk_work_authorization"):
            auth_parts: List[str] = []
            if citizenships:
                auth_parts.append(f"Citizenship: {', '.join(citizenships)}")
            if wa.get("eu_work_permit"):
                auth_parts.append("EU work permit confirmed")
            if wa.get("us_work_authorization"):
                auth_parts.append(f"US: {wa.get('us_work_authorization')}")
            if wa.get("uk_work_authorization"):
                auth_parts.append(f"UK: {wa.get('uk_work_authorization')}")
            items.append(
                {
                    "question_trigger": "work authorization / remote B2B & visa status",
                    "tags": ["visa", "b2b", "remote", "authorization"],
                    "answer": "; ".join(auth_parts),
                }
            )
        return items

    def _normalize_vault(self, vault: Dict[str, Any], profile: CandidateProfile) -> Dict[str, Any]:
        """Normalizes vault fields without hardcoding citizenship, visa assumptions, or fake salary targets."""
        data = dict(vault or {})
        raw_md = profile.raw_markdown or ""
        parsed_md = self.parse_profile_from_md(raw_md) if raw_md else {}
        ps = dict(profile.parsed_skills or {})

        cand = dict(data.get("candidate") or {})
        raw_full_name = cand.get("full_name") or profile.full_name or parsed_md.get("full_name") or ""
        full_name = sanitize_person_name(raw_full_name) or sanitize_person_name(profile.full_name or "") or sanitize_person_name(parsed_md.get("full_name") or "")
        parts = full_name.split()
        cand["first_name"] = parts[0] if parts else ""
        cand["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
        cand["full_name"] = full_name
        cand["experience_years"] = profile.experience_years
        cand["experience_status"] = ps.get("experience_status") or (
            "confirmed" if profile.experience_years is not None else "unknown"
        )
        cand.setdefault("headline", ps.get("headline") or parsed_md.get("headline") or "")
        cand.setdefault("email", profile.email if profile.email != "candidate@example.com" else "")
        cand.setdefault("phone", profile.phone if "+000" not in str(profile.phone or "") else "")
        if not cand.get("phone") and parsed_md.get("phone"):
            cand["phone"] = parsed_md["phone"]

        loc = cand.get("location")
        if not isinstance(loc, dict):
            loc = {}
        raw_loc_str = re.sub(r"[*_`]+", "", (profile.location or parsed_md.get("location") or "")).strip()
        if loc.get("city"):
            loc["city"] = re.sub(r"[*_`]+", "", str(loc["city"])).strip()
        if loc.get("country"):
            loc["country"] = re.sub(r"[*_`]+", "", str(loc["country"])).strip()
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
        parsed_edu = [e for e in (parsed_md.get("education") or []) if not is_corrupted_education_entry(e)]
        has_corrupted_edu = isinstance(edu, list) and any(is_corrupted_education_entry(e) for e in edu)
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
        if has_corrupted_edu or is_fragmented_edu or not isinstance(edu, list) or not edu:
            edu = parsed_edu or [e for e in (ps.get("education") or []) if not is_corrupted_education_entry(e)]
        else:
            edu = [e for e in edu if not is_corrupted_education_entry(e)]
        data["education"] = edu

        if not isinstance(data.get("projects"), list) or not data.get("projects"):
            data["projects"] = parsed_md.get("projects") or []
        if not isinstance(data.get("certifications"), list) or not data.get("certifications"):
            data["certifications"] = (
                parsed_md.get("certifications")
                or ps.get("courses_and_certifications")
                or []
            )

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

        is_guest_owner = (owner_email or "").strip().lower() == "guest@talentflow.local"
        eff_uid = None if is_guest_owner else user_id
        target_prof = self.get_profile_record(owner_email=owner_email, user_id=eff_uid)

        with Session(engine) as session:
            profile = session.get(CandidateProfile, target_prof.id) if target_prof and target_prof.id else None
            if not profile:
                profile = self._ensure_seeded()
                profile = session.get(CandidateProfile, profile.id)

            if eff_uid is not None and profile.user_id is None:
                profile.user_id = eff_uid

            if raw_md is not None:
                profile.raw_markdown = raw_md

            cand_in = save_copy.get("candidate")
            if isinstance(cand_in, dict):
                if cand_in.get("full_name"):
                    profile.full_name = str(cand_in["full_name"]).strip()
                elif cand_in.get("first_name") or cand_in.get("last_name"):
                    profile.full_name = f"{cand_in.get('first_name', '')} {cand_in.get('last_name', '')}".strip()
                if "email" in cand_in and cand_in.get("email") is not None:
                    profile.email = str(cand_in["email"]).strip()
                if "phone" in cand_in and cand_in.get("phone") is not None:
                    profile.phone = str(cand_in["phone"]).strip()
                loc_in = cand_in.get("location")
                if isinstance(loc_in, dict):
                    loc_str = ", ".join(p for p in [str(loc_in.get("city") or "").strip(), str(loc_in.get("country") or "").strip()] if p)
                    if loc_str:
                        profile.location = loc_str
                links_in = cand_in.get("links")
                if isinstance(links_in, dict):
                    if "linkedin" in links_in:
                        profile.linkedin_url = str(links_in.get("linkedin") or "").strip()
                    if "github" in links_in:
                        profile.github_url = str(links_in.get("github") or "").strip()

            existing_ps = dict(profile.parsed_skills or {})
            taxonomy = matcher_service.parse_skills_markdown(profile.raw_markdown)
            if isinstance(cand_in, dict) and cand_in.get("headline") is not None:
                taxonomy["headline"] = str(cand_in["headline"]).strip()
            if isinstance(save_copy.get("skills"), dict) and isinstance(save_copy["skills"].get("core"), list):
                cleaned_core = dedupe_skills_case_insensitive([str(x) for x in save_copy["skills"]["core"]])
                save_copy["skills"]["core"] = cleaned_core
                taxonomy["all_skills"] = cleaned_core
            for preserve_key in (
                "user_uploaded",
                "owner_email",
                "user_id",
                "education",
                "courses_and_certifications",
                "eligible_internships",
                "target_industry",
                "detected_industry",
                "primary_role",
                "adjacent_roles",
                "verified_skills",
                "max_allowed_years",
                "seniority_level",
                "years_of_experience",
                "experience_status",
                "internship_tracks",
            ):
                if preserve_key in existing_ps:
                    taxonomy[preserve_key] = existing_ps[preserve_key]

            if isinstance(save_copy.get("education"), list):
                taxonomy["education"] = save_copy["education"]
            if isinstance(save_copy.get("projects"), list):
                taxonomy["projects"] = save_copy["projects"]
            if isinstance(save_copy.get("certifications"), list):
                taxonomy["courses_and_certifications"] = save_copy["certifications"]
            if isinstance(cand_in, dict) and isinstance(cand_in.get("languages"), list):
                cleaned_langs = filter_spoken_language_entries(cand_in["languages"])
                cand_in["languages"] = cleaned_langs
                taxonomy["spoken_languages"] = [
                    f"{l['language']} ({l['proficiency']})" if l.get("proficiency") else l["language"]
                    for l in cleaned_langs
                ]

            if owner_email and not is_guest_owner:
                taxonomy["owner_email"] = owner_email.strip().lower()
            if eff_uid is not None:
                taxonomy["user_id"] = eff_uid
            taxonomy["ground_truth_vault"] = save_copy
            profile.parsed_skills = taxonomy
            profile.updated_at = utc_now()
            session.add(profile)

            self.sync_relational_children(
                session,
                profile,
                work_history=save_copy["work_history"] if isinstance(save_copy.get("work_history"), list) else None,
                education_entries=save_copy["education"] if isinstance(save_copy.get("education"), list) else None,
            )
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
        cleaned_md = strip_yaml_frontmatter(md_content or "")
        cleaned_md = cleaned_md.replace("\uf0b7", "- ").replace("", "- ").replace("▪", "- ")
        lines = cleaned_md.splitlines()
        header_block = "\n".join(lines[:15])

        for line in lines:
            s = line.strip()
            if s.startswith("# ") and not s.startswith("## "):
                h1 = re.sub(r"[*_`]+", "", s[2:]).strip()
                parts = re.split(r"\s+[—–-]\s+", h1, maxsplit=1)
                cand_h1 = sanitize_person_name(parts[0])
                if cand_h1:
                    result["full_name"] = cand_h1
                if len(parts) > 1:
                    result["headline"] = parts[1].strip()
                break

        email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", cleaned_md)
        if email_m:
            result["email"] = email_m.group(0)

        phone_m = re.search(r"(?:Phone|ტელეფონი|Tel)\**\s*:\**\s*([+\d \t()-]{7,22})", cleaned_md, re.I)
        if not phone_m:
            phone_m = re.search(
                r"(?<!\d)(\+\d{1,3}[\s.-]?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4})(?!\d)",
                header_block,
            )
        if phone_m:
            result["phone"] = re.sub(r"[*_`]+", "", phone_m.group(1)).strip(" -\t\r\n")

        loc_m = re.search(r"(?:Location|მდებარეობა)\**\s*:\**\s*([^\n]+)", cleaned_md, re.I)
        if not loc_m:
            loc_m = re.search(
                r"(?:^|[•|])\s*([A-Z][A-Za-zÀ-ÿ .-]{1,28},\s*[A-Z][A-Za-zÀ-ÿ .-]{1,28})\s*(?:$|[•|])",
                header_block,
                re.M,
            )
        if loc_m:
            result["location"] = re.sub(r"[*_`]+", "", loc_m.group(1)).strip(" :-–—•|")

        name_m = re.search(
            r"(?:\*\*Author:\*\*|\*\*Name:\*\*|Full Name|Author|Candidate|სახელი და გვარი)\**\s*:\**\s*([^\n\r*]+)",
            cleaned_md,
            re.I,
        )
        if name_m:
            cand_val = sanitize_person_name(name_m.group(1))
            if cand_val:
                result["full_name"] = cand_val

        notice_m = re.search(
            r"(?:Availability\s*/\s*Notice\s*Period|Notice\s*Period|Availability|Earliest\s*Start|დაწყების\s*თარიღი)\**\s*:\**\s*([^\n]+)",
            cleaned_md,
            re.I,
        )
        if notice_m:
            result["notice_period"] = re.sub(r"[*_`]+", "", notice_m.group(1)).strip()

        gh_m = re.search(r"https?://(?:www\.)?github\.com/[^\s)]+", cleaned_md, re.I)
        if gh_m:
            result["github_url"] = gh_m.group(0)
        li_m = re.search(r"https?://(?:www\.)?linkedin\.com/in/[^\s)]+", cleaned_md, re.I)
        if li_m:
            result["linkedin_url"] = li_m.group(0)

        _PLAIN_SEC_RE = re.compile(
            r"^(?:core\s+competencies(?:\s*&\s*technical\s+skills)?|technical\s+skills(?:\s*&\s*stack)?|"
            r"core\s+skills|skills|summary|professional\s+summary|work\s+experience|professional\s+experience|"
            r"experience|employment\s+history|projects|relevant\s+projects|technical\s+projects|"
            r"education(?:\s*&\s*(?:technical\s+training|specialized\s+training|certifications))?|"
            r"courses\s*&\s*certifications|certifications|languages|spoken\s+languages)\s*:?$",
            re.I,
        )
        _DATE_TAIL_RE = re.compile(
            r"^(.*?)\s+((?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+)?(?:19|20)\d{2}\s*[–—\-]\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+)?(?:(?:19|20)\d{2}|Present|Current|Now))\s*$",
            re.I,
        )

        def _is_section_heading(stripped_line: str) -> bool:
            if stripped_line.startswith("## ") and not stripped_line.startswith("### "):
                return True
            if stripped_line.startswith("# ") and not stripped_line.startswith("## "):
                return True
            return bool(_PLAIN_SEC_RE.match(stripped_line))

        summary_lines = []
        in_summary = False
        for line in lines:
            s = line.strip()
            if _is_section_heading(s):
                low_sh = s.lower()
                in_summary = any(w in low_sh for w in ["summary", "about", "შესახებ", "მიმოხილვა", "პროფილი"])
                continue
            if in_summary and s and not s.startswith("#"):
                summary_lines.append(s)
        if summary_lines:
            result["summary"] = " ".join(summary_lines)

        result["skills"] = self.extract_skills_from_md(cleaned_md)

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
        current_exp_company = ""
        current_proj = None
        current_edu = None
        last_edu_target: Optional[str] = None  # "edu" or "cert" for PDF-wrapped continuation lines

        def _flush_edu() -> None:
            nonlocal current_edu
            if current_edu:
                if not is_corrupted_education_entry(current_edu):
                    mods = [m for m in (current_edu.get("modules") or []) if m and not _AI_META_PROSE_RE.search(m)]
                    current_edu["modules"] = mods
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

        def _join_wrapped(prev: str, cont: str) -> str:
            if not prev:
                return cont
            # PDF extraction sometimes breaks Title-Case words mid-word (e.g. "Qua" + "ntitative");
            # never glue ALL-CAPS acronyms like JSON, SQL, API, HTTP to the next word!
            last_tok = prev.split()[-1]
            if (
                len(last_tok) in (2, 3, 4)
                and last_tok.isalpha()
                and last_tok[0].isupper()
                and last_tok[1:].islower()
                and re.match(r"^[a-z]{3,}", cont)
                and last_tok.lower() not in ("the", "and", "for", "via", "per", "has", "was", "are", "not", "all", "new", "our")
            ):
                return f"{prev}{cont}"
            return f"{prev} {cont}"

        for line in lines:
            s = line.strip()
            if _is_section_heading(s):
                low_h = s.lower()
                in_exp = any(w in low_h for w in ["experience", "history", "work", "გამოცდილება", "სამუშაო"])
                in_proj = any(w in low_h for w in ["project", "portfolio", "პროექტ"])
                in_edu = any(w in low_h for w in ["education", "academic", "university", "განათლება", "სწავლა"])
                in_cert = (not in_edu) and any(w in low_h for w in ["training", "certif", "course", "bootcamp", "სერტიფიკატ", "კურს"])
                in_lang = any(w in low_h for w in ["language", "spoken", "ენებ"]) and "skill" not in low_h
                if not in_exp and current_job:
                    work_history.append(current_job)
                    current_job = None
                    current_exp_company = ""
                if not in_proj:
                    _flush_proj()
                if not in_edu:
                    _flush_edu()
                    last_edu_target = None
                continue

            if in_exp:
                if not s or re.fullmatch(r"[-*_=\s]{2,}", s) or _AI_META_PROSE_RE.search(s):
                    continue
                if s.startswith("### "):
                    if current_job:
                        work_history.append(current_job)
                    header = re.sub(r"[*_`]+", "", s[4:]).strip()
                    parts = [p.strip() for p in re.split(r"[|@—–]", header, maxsplit=1)]
                    role = parts[0]
                    comp = parts[1] if len(parts) > 1 else "Organization"
                    current_exp_company = comp if comp != "Organization" else current_exp_company
                    current_job = {
                        "role": role,
                        "company": comp,
                        "location": "",
                        "start_date": "",
                        "end_date": "Present",
                        "highlights": [],
                    }
                elif s.startswith(("-", "*", "•")) and not (s.startswith("*") and not s.startswith("* ") and s.endswith("*")):
                    if current_job:
                        bullet = re.sub(r"^[-*•]\s*", "", s).strip()
                        bullet = re.sub(r"[*_`]+", "", bullet).strip()
                        if bullet and not re.fullmatch(r"[-*_•–—.\s]+", bullet):
                            current_job["highlights"].append(bullet)
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
                elif (dt_m := _DATE_TAIL_RE.match(re.sub(r"[*_`]+", "", s).strip())) and len(s) < 120:
                    head_txt = dt_m.group(1).strip(" |—–-")
                    date_rng = dt_m.group(2).strip()
                    dt_parts = [p.strip() for p in re.split(r"\s*[–—\-]\s*", date_rng, maxsplit=1)]
                    s_dt = dt_parts[0]
                    e_dt = dt_parts[1] if len(dt_parts) > 1 else ""
                    if any(sep in head_txt for sep in (" — ", " – ", " | ", " - ")):
                        h_parts = [p.strip() for p in re.split(r"\s+(?:—|–|\||-)\s+", head_txt, maxsplit=1)]
                        if current_job:
                            work_history.append(current_job)
                        current_exp_company = h_parts[1]
                        current_job = {
                            "role": h_parts[0],
                            "company": h_parts[1],
                            "location": "",
                            "start_date": s_dt,
                            "end_date": e_dt,
                            "highlights": [],
                        }
                    else:
                        # Distinguish company header (e.g. "EPAM Systems Aug 2024 – Jun 2025") vs sub-role ("Junior Software Testing Engineer Jan 2025 – Jun 2025")
                        is_role_line = bool(re.search(
                            r"\b(?:engineer|specialist|intern|trainee|analyst|developer|tester|qa|manager|coordinator|lead|consultant|director|officer|receptionist|accountant|designer|architect)\b",
                            head_txt,
                            re.I,
                        ))
                        if not is_role_line and len(head_txt.split()) <= 5:
                            current_exp_company = head_txt
                        else:
                            if current_job:
                                work_history.append(current_job)
                            current_job = {
                                "role": head_txt,
                                "company": current_exp_company or "Organization",
                                "location": "",
                                "start_date": s_dt,
                                "end_date": e_dt,
                                "highlights": [],
                            }
                elif current_job and current_job["highlights"]:
                    # PDF line-wrapped continuation of the previous highlight bullet
                    cont = re.sub(r"[*_`]+", "", s).strip()
                    if cont:
                        current_job["highlights"][-1] = _join_wrapped(current_job["highlights"][-1], cont)

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
                elif current_proj and s.startswith(("-", "*", "•")):
                    bullet = re.sub(r"^[-*•]\s*", "", s).strip()
                    bullet = re.sub(r"[*_`]+", "", bullet).strip()
                    if bullet and not re.fullmatch(r"[-*_•–—.\s]+", bullet):
                        current_proj["highlights"].append(bullet)

            elif in_edu:
                if re.fullmatch(r"[-*_=\s]{2,}", s) or not s or _AI_META_PROSE_RE.search(s):
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
                    clean_e = re.sub(r"^[-*•]\s*", "", s)
                    clean_e = re.sub(r"[*_`]+", "", clean_e).strip()
                    if not clean_e or re.fullmatch(r"[-*_•–—.\s]+", clean_e) or _AI_META_PROSE_RE.search(clean_e):
                        continue
                    if s.startswith("**") and not s.startswith("* "):
                        if "•" in clean_e:
                            inst_p, loc_p = [x.strip() for x in clean_e.split("•", 1)]
                            current_edu["institution"] = inst_p
                            current_edu["location"] = loc_p
                        else:
                            current_edu["institution"] = clean_e
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
                                split_mods = [m.strip() for m in re.split(r"\s*[,;/]\s*", val) if m.strip()]
                                current_edu["modules"].extend(m for m in split_mods if m not in current_edu["modules"])
                                current_edu["field_of_study"] = (
                                    f"{current_edu['field_of_study']}; {val}".strip("; ")
                                    if current_edu["field_of_study"]
                                    else val
                                )
                        else:
                            current_edu["modules"].append(clean_e.rstrip("."))
                else:
                    # Bullet-only or PDF-extracted Education section (without ### subheadings)
                    is_bullet_start = bool(re.match(r"^[-*•]\s+", s))
                    clean_e = re.sub(r"^[-*•]\s*", "", s)
                    clean_e = re.sub(r"[*_`]+", "", clean_e).strip()
                    if not clean_e or re.fullmatch(r"[-*_•–—.\s]+", clean_e) or _AI_META_PROSE_RE.search(clean_e):
                        continue
                    # Route "Technical Programs:" / "Certifications:" / "Courses:" bullets to certifications
                    if re.match(r"^(?:technical\s+programs|specialized\s+training|courses|certifications|bootcamps?)\s*:", clean_e, re.I):
                        prog_body = re.sub(r"^(?:technical\s+programs|specialized\s+training|courses|certifications|bootcamps?)\s*:\s*", "", clean_e, flags=re.I).strip()
                        for prog_item in [p.strip() for p in re.split(r"\s*•\s*", prog_body) if p.strip()]:
                            certifications_list.append(prog_item)
                        last_edu_target = "cert"
                        continue
                    # Attach wrapped continuation lines (non-bullet lines after a bullet) cleanly
                    if not is_bullet_start and last_edu_target == "cert" and certifications_list:
                        joined = _join_wrapped(certifications_list[-1], clean_e)
                        if " • " in joined:
                            parts_c = [p.strip() for p in joined.split(" • ") if p.strip()]
                            certifications_list[-1] = parts_c[0]
                            certifications_list.extend(parts_c[1:])
                        else:
                            certifications_list[-1] = joined
                        continue
                    if not is_bullet_start and last_edu_target == "edu" and education_items:
                        prev_e = education_items[-1]
                        if re.fullmatch(r"(?:19|20)\d{2}(?:\s*[–\-]\s*(?:(?:19|20)\d{2}|present|current))?", clean_e, re.I):
                            prev_e["dates"] = clean_e
                            yrs = [int(y) for y in re.findall(r"\b(19\d{2}|20[0-3]\d)\b", clean_e)]
                            if yrs:
                                prev_e["graduation_year"] = yrs[-1]
                                prev_e["is_student_or_recent_grad"] = yrs[-1] >= 2022 or "present" in clean_e.lower()
                            continue
                        if not re.search(r"\b(?:university|institute|college|academy|b\.?sc|m\.?sc|bachelor|master|phd|უნივერსიტეტ)\b", clean_e, re.I):
                            prev_e["field_of_study"] = _join_wrapped(prev_e.get("field_of_study") or "", clean_e)
                            prev_e["focus"] = prev_e["field_of_study"]
                            continue
                    # Skip standalone garbage/meta/honors lines if no degree/university cue
                    if is_corrupted_education_entry({"degree": clean_e, "institution": ""}):
                        continue
                    # Parse structured bullet e.g. "M.Sc. in Economics - Tbilisi State University (TSU) | 2026 – Present — Focus on ..."
                    focus_txt = ""
                    main_part = clean_e
                    if " — " in clean_e:
                        main_part, focus_txt = [p.strip() for p in clean_e.split(" — ", 1)]
                    dates_txt = ""
                    if "|" in main_part:
                        left_p, right_p = [p.strip() for p in main_part.split("|", 1)]
                        if re.search(r"\b(?:19|20)\d{2}\b", right_p):
                            main_part = left_p
                            dates_txt = right_p
                    deg_txt, inst_txt = main_part, ""
                    if " - " in main_part:
                        d_p, i_p = [p.strip() for p in main_part.split(" - ", 1)]
                        deg_txt, inst_txt = d_p, i_p
                    elif " – " in main_part and not re.search(r"\b(?:19|20)\d{2}\b", main_part.split(" – ", 1)[1]):
                        d_p, i_p = [p.strip() for p in main_part.split(" – ", 1)]
                        deg_txt, inst_txt = d_p, i_p
                    yr_matches = re.findall(r"\b(19\d{2}|20[0-3]\d)\b", dates_txt or clean_e)
                    grad_yr = int(yr_matches[-1]) if yr_matches else None
                    edu_obj = {
                        "degree": deg_txt.strip(),
                        "institution": inst_txt.strip(),
                        "location": "",
                        "dates": dates_txt or (yr_matches[-1] if yr_matches else ""),
                        "graduation_year": grad_yr,
                        "gpa": "",
                        "modules": [],
                        "field_of_study": focus_txt,
                        "focus": focus_txt,
                        "is_student_or_recent_grad": bool(
                            (grad_yr and grad_yr >= 2022) or "present" in (dates_txt or clean_e).lower()
                        ),
                    }
                    if not is_corrupted_education_entry(edu_obj):
                        education_items.append(edu_obj)
                        last_edu_target = "edu"

            elif in_cert:
                if re.fullmatch(r"[-*_=\s]{2,}", s) or not s or s.startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                if s.startswith(("- ", "* ", "• ")) and indent == 0:
                    clean_c = re.sub(r"^[-*•]\s+", "", s)
                    clean_c = re.sub(r"[*_`]+", "", clean_c).strip()
                    if clean_c:
                        certifications_list.append(clean_c)
                elif s.startswith(("- ", "* ", "• ")) and indent >= 2 and certifications_list:
                    detail = re.sub(r"^[-*•]\s+", "", s)
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
                clean_l = re.sub(r"^[-*•]\s*", "", s)
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
        from ..services.profile_service import profile_service
        return profile_service.upsert_candidate_profile(
            md_content, mark_uploaded=True, owner_email=owner_email, user_id=user_id
        )

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

    def get_cv_variants(self) -> Dict[str, Any]:
        return self.get_data().get("cv_variants", {})


profile_repository = ProfileRepository()
ground_truth_store = profile_repository
