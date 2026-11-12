import json
import logging
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from ..config import GEMINI_API_KEY, GEMINI_MODEL, SKILLS_MD_FILE, GROUND_TRUTH_FILE
from ..db.database import engine, init_db
from ..db.models import CandidateProfile, utc_now
from .matcher_service import matcher_service

logger = logging.getLogger(__name__)


class ExtractedSkillsTaxonomy(BaseModel):
    qa_automation: List[str] = Field(default_factory=list)
    manual_qa: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    api_and_performance: List[str] = Field(default_factory=list)
    cicd_and_devops: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    spoken_languages: List[str] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)
    education: List[Dict[str, Any]] = Field(default_factory=list)
    courses_and_certifications: List[str] = Field(default_factory=list)
    all_skills: List[str] = Field(default_factory=list)


class ParsedCandidateProfileSchema(BaseModel):
    full_name: str = "Candidate"
    headline: str = "Specialist"
    primary_role: str = "Specialist"
    detected_industry: str = "General Professional"
    adjacent_roles: List[str] = Field(default_factory=list)
    verified_skills: List[str] = Field(default_factory=list)
    eligible_internships: bool = True
    internship_tracks: List[str] = Field(default_factory=list)
    email: str = "candidate@example.com"
    phone: str = ""
    location: str = ""
    github_url: str = ""
    linkedin_url: str = ""
    experience_years: float = 1.5
    max_allowed_years: float = 2.0
    seniority_level: str = "JUNIOR"
    target_industry: str = "general_professional"
    parsed_skills: ExtractedSkillsTaxonomy = Field(default_factory=ExtractedSkillsTaxonomy)


_DOMAIN_PROFILE_CATALOG: List[Dict[str, Any]] = [
    {
        "target_industry": "logistics_supply_chain",
        "detected_industry": "Supply Chain & Logistics",
        "primary_role": "Logistics & Supply Chain Coordinator",
        "adjacent_roles": ["Procurement Specialist", "Dispatch & Freight Operations", "Inventory & Warehouse Analyst", "Operations Coordinator"],
        "signals": ["logistics", "supply chain", "procurement", "warehouse", "freight", "dispatch", "customs", "incoterms", "ლოჯისტიკ", "შესყიდვ", "მომარაგებ"],
    },
    {
        "target_industry": "finance_accounting",
        "detected_industry": "Finance & Accounting",
        "primary_role": "Junior Financial Analyst & Accountant",
        "adjacent_roles": ["Audit Associate", "Billing & Reconciliation Specialist", "Operations & Reporting Analyst", "Treasury Coordinator"],
        "signals": ["accounting", "accountant", "financial analyst", "bookkeeping", "ifrs", "1c accounting", "oris", "ბუღალტ", "ფინანს", "აუდიტ"],
    },
    {
        "target_industry": "data_analytics",
        "detected_industry": "Data & Business Analytics",
        "primary_role": "Data & BI Analyst",
        "adjacent_roles": ["Data Quality Engineer", "Operations Reporting Specialist", "Junior SQL Developer", "QA & Data Validation Analyst"],
        "signals": ["data analyst", "power bi", "tableau", "looker", "etl", "data quality", "bi developer", "ანალიტიკოს"],
    },
    {
        "target_industry": "marketing_growth",
        "detected_industry": "Marketing & Digital Growth",
        "primary_role": "Digital Marketing Specialist",
        "adjacent_roles": ["SMM & Content Coordinator", "Performance Marketing Associate", "E-Commerce Coordinator", "Brand & PR Assistant"],
        "signals": ["digital marketing", "seo", "smm", "meta ads", "google ads", "copywriter", "content manager", "მარკეტინგ"],
    },
    {
        "target_industry": "sales_bd",
        "detected_industry": "Sales & Business Development",
        "primary_role": "B2B Sales & Account Specialist",
        "adjacent_roles": ["Client Onboarding Specialist", "Customer Success Associate", "CRM & Lead Operations Specialist", "Business Support Coordinator"],
        "signals": ["sales manager", "business development", "b2b sales", "account executive", "lead generation", "გაყიდვ"],
    },
    {
        "target_industry": "hr_recruiting",
        "detected_industry": "HR & Talent Acquisition",
        "primary_role": "HR & Talent Acquisition Specialist",
        "adjacent_roles": ["People Operations Coordinator", "Office & Admin Coordinator", "Onboarding Specialist", "Training Coordinator"],
        "signals": ["recruiter", "human resources", "talent acquisition", "hr generalist", "hris", "ადამიანური რესურს", "რეკრუტ"],
    },
    {
        "target_industry": "public_admin_legal",
        "detected_industry": "Public Administration & Legal",
        "primary_role": "Junior Legal & Public Policy Specialist",
        "adjacent_roles": ["Compliance & Audit Coordinator", "Public Procurement Officer", "Administrative Department Specialist", "Contract Assistant"],
        "signals": ["public administration", "lawyer", "legal counsel", "compliance", "procurement law", "იურისტ", "საჯარო მმართველ"],
    },
    {
        "target_industry": "receptionist_hospitality",
        "detected_industry": "Hospitality & Front Office",
        "primary_role": "Front Desk Receptionist & Hospitality Specialist",
        "adjacent_roles": ["Guest Relations Coordinator", "Hotel Reservations Agent", "Office Administrator", "Customer Service Specialist"],
        "signals": ["receptionist", "hotel", "opera pms", "fidelio", "hospitality", "guest relations", "მიმღები"],
    },
    {
        "target_industry": "healthcare_hospital",
        "detected_industry": "Healthcare & Medical Admin",
        "primary_role": "Hospital Patient Coordinator & Medical Receptionist",
        "adjacent_roles": ["Clinic Administrator", "Medical Insurance Coordinator", "Front Desk Coordinator", "Patient Support Specialist"],
        "signals": ["patient coordinator", "medical receptionist", "hospital", "clinic", "ehr", "emr", "სამედიცინო"],
    },
    {
        "target_industry": "customer_service",
        "detected_industry": "Customer Support & Client Success",
        "primary_role": "Customer Service & Client Care Specialist",
        "adjacent_roles": ["Technical Support Specialist L1/L2", "Client Onboarding Coordinator", "Manual QA / Support Specialist", "Operations Assistant"],
        "signals": ["customer service", "client care", "zendesk", "intercom", "omnichannel support", "მომხმარებელთა მხარდაჭერა"],
    },
    {
        "target_industry": "software_engineering",
        "detected_industry": "Software Engineering & Backend",
        "primary_role": "Junior Software / Python Engineer",
        "adjacent_roles": ["QA Automation Engineer (SDET)", "Technical Support Engineer L2/L3", "Data & ETL Engineer", "DevOps / Junior Cloud Engineer"],
        "signals": ["backend developer", "frontend developer", "full stack", "fastapi", "django", "react developer", "პროგრამისტი", "დეველოპერი"],
    },
    {
        "target_industry": "qa_tech",
        "detected_industry": "IT & Software QA",
        "primary_role": "QA Automation & Software Test Engineer",
        "adjacent_roles": ["Technical Support Engineer L2/L3", "Data Quality Analyst", "Junior Python / Automation Developer", "IT Operations Specialist"],
        "signals": ["qa", "quality assurance", "tester", "playwright", "selenium", "cypress", "pytest", "sdet", "ტესტ"],
    },
]


class ProfileService:
    """
    Production Skills Ingestion Service (POST /api/profile/upload-skills):
    - Ingests uploaded .md or .txt files.
    - Calls Gemini 2.5 Flash via google-genai with a strict Pydantic JSON schema (ParsedCandidateProfileSchema)
      to extract personal info, technical toolset, framework proficiencies, and measurable achievements.
    - Upserts the data into CandidateProfile in the relational SQLite/PostgreSQL database.
    """

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.model = GEMINI_MODEL
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"ProfileService Gemini client fallback: {e}")

    def extract_structured_profile(self, raw_markdown: str) -> ParsedCandidateProfileSchema:
        text = raw_markdown or ""
        lower_text = text.lower()

        # Deterministic extraction baseline
        taxonomy_dict = matcher_service.parse_skills_markdown(text)
        full_name = "Candidate"
        target_industry = "qa_tech"
        headline = "QA Engineer"
        email = "candidate@example.com"
        phone = "+000 000 0000"
        location = "Tbilisi, Georgia (Remote / Abroad)"
        github_url = "https://github.com/example-candidate"
        linkedin_url = "https://linkedin.com/in/example-candidate"

        # 1. Name extraction
        name_m = re.search(r"(?:\*\*Author:\*\*|\*\*Name:\*\*|Full Name|Author|Candidate|სახელი და გვარი|Name)\**\s*:\**\s*([^\n\r*]+)", text, re.I)
        if name_m:
            candidate_cand = name_m.group(1).strip()
            if len(candidate_cand) > 2 and not any(w in candidate_cand.lower() for w in ["http", "api", "case study"]):
                full_name = candidate_cand
        else:
            # Check # heading, but skip if it is a project / case study title
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    candidate_cand = s[2:].strip()
                    parts = re.split(r"\s+[—–-]\s+", candidate_cand, maxsplit=1)
                    cand_first = parts[0].strip()
                    # Skip project / case study headings
                    if not any(w in cand_first.lower() for w in ["api", "case study", "project", "test", "sticker", "portfolio", "guide", "docs", "documentation"]):
                        full_name = cand_first
                    break

        # 2. Universal Weighted-Evidence Domain, Primary Role & Adjacent Role Detection
        # Score by header/headline (+12), verified skills (+4), and body (+1) so mentioning
        # e.g. "Exactpro Systems (Financial Systems)" in a QA Engineer resume NEVER overrides QA -> Finance!
        target_industry = "general_professional"
        detected_industry = "General Business & Operations"
        primary_role = "Operations & Administrative Specialist"
        adjacent_roles = ["Project Coordinator", "Operations Analyst", "Customer Support Specialist", "Administrative Assistant"]

        header_lines = "\n".join(text.splitlines()[:12]).lower()
        skills_blob = " ".join(str(x).lower() for x in (taxonomy_dict.get("all_skills") or []))
        has_qa_tax = bool(taxonomy_dict.get("qa_automation") or taxonomy_dict.get("manual_qa"))

        best_score = 0
        best_dom: Optional[Dict[str, Any]] = None
        for dom in _DOMAIN_PROFILE_CATALOG:
            score = 0
            for sig in dom["signals"]:
                if len(sig) <= 2:
                    hit_hdr = bool(re.search(r"\b" + re.escape(sig) + r"\b", header_lines))
                    hit_sk = bool(re.search(r"\b" + re.escape(sig) + r"\b", skills_blob))
                    hit_body = bool(re.search(r"\b" + re.escape(sig) + r"\b", lower_text))
                else:
                    hit_hdr = sig in header_lines
                    hit_sk = sig in skills_blob
                    hit_body = sig in lower_text
                if hit_hdr:
                    score += 12
                if hit_sk:
                    score += 4
                if hit_body:
                    score += 1
            if dom["target_industry"] == "qa_tech" and has_qa_tax:
                score += 6 * (len(taxonomy_dict.get("qa_automation") or []) + len(taxonomy_dict.get("manual_qa") or []))
            if score > best_score:
                best_score = score
                best_dom = dom

        if best_dom and best_score > 0:
            target_industry = best_dom["target_industry"]
            detected_industry = best_dom["detected_industry"]
            primary_role = best_dom["primary_role"]
            adjacent_roles = list(best_dom["adjacent_roles"])

        # Refine QA vs General headline and extract explicit Target Role / Headline if authored in skills.md
        if target_industry == "qa_tech":
            if any(w in lower_text for w in ["portfolio project", "entry-level", "starter", "junior", "1.5"]):
                headline = "QA Engineer (Test Design & API Quality)"
                primary_role = headline
            else:
                headline = primary_role
            # Dynamically adapt QA adjacent roles based on candidate's verified skills
            all_sk_l = " ".join(taxonomy_dict.get("all_skills") or []).lower()
            dyn_adj = []
            if any(k in all_sk_l for k in ["sql", "postgres", "postman", "api"]):
                dyn_adj.append("Technical Support Engineer L2/L3")
                dyn_adj.append("Data Quality Analyst")
            if any(k in all_sk_l for k in ["python", "typescript", "javascript", "playwright"]):
                dyn_adj.append("Junior Automation / Python Developer")
            if any(k in all_sk_l for k in ["linux", "docker", "git", "ci"]):
                dyn_adj.append("IT Operations Specialist")
            if dyn_adj:
                adjacent_roles = list(dict.fromkeys(dyn_adj + adjacent_roles))[:4]
        else:
            headline = primary_role

        # Check explicit headline / role in markdown or `# Full Name — Role Title` header
        headline_m = re.search(r"(?:Headline|Target Role|Primary Role|პოზიცია|როლი)\**\s*:\**\s*([^\n]+)", text, re.I)
        if headline_m:
            headline = headline_m.group(1).strip()
            primary_role = headline
        else:
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    parts = re.split(r"\s+[—–-]\s+", s[2:].strip(), maxsplit=1)
                    if len(parts) == 2 and len(parts[1].strip()) > 2:
                        primary_role = parts[1].strip()
                        headline = primary_role
                    break

        email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_m:
            email = email_m.group(0)

        phone_m = re.search(r"(?:Phone|ტელეფონი|Tel)\**\s*:\**\s*([+\d \t()-]{7,22})", text, re.I)
        if phone_m:
            phone = phone_m.group(1).strip(" -\t\r\n")

        loc_m = re.search(r"(?:Location|მდებარეობა)\**\s*:\**\s*([^\n]+)", text, re.I)
        if loc_m:
            location = loc_m.group(1).strip()

        gh_m = re.search(r"https?://(?:www\.)?github\.com/[^\s)]+", text, re.I)
        if gh_m:
            github_url = gh_m.group(0)

        li_m = re.search(r"https?://(?:www\.)?linkedin\.com/in/[^\s)]+", text, re.I)
        if li_m:
            linkedin_url = li_m.group(0)

        achievements: List[str] = []
        education_entries: List[Dict[str, Any]] = []
        courses_certs: List[str] = []

        in_edu_sec = False
        in_courses_sec = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("## "):
                lh = s.lower()
                in_edu_sec = any(k in lh for k in ("education", "academic", "university", "განათლება"))
                in_courses_sec = any(k in lh for k in ("course", "certif", "bootcamp", "training", "კურს", "სერტიფიკატ"))
                continue
            if s.startswith(("- ", "* ")) and any(ch.isdigit() for ch in s) and not in_edu_sec:
                achievements.append(re.sub(r"^[-*]\s*", "", s))

            clean_line = re.sub(r"^[-*#\s]+", "", s).strip()
            clean_line = re.sub(r"[*_`]+", "", clean_line).strip()
            if not clean_line:
                continue

            if in_courses_sec or re.search(
                r"\b(?:istqb|aws\s+certified|coursera|udemy|bootcamp|certificate|certification|tbc\s+academy|it\s+academy|epam\s+lab|კურსი|სერტიფიკატ)\b",
                clean_line,
                re.I,
            ):
                if len(clean_line) >= 4 and clean_line not in courses_certs and not clean_line.lower().startswith("http"):
                    courses_certs.append(clean_line[:140])

            looks_like_edu = in_edu_sec or bool(
                re.search(
                    r"\b(?:b\.?s\.?c?|m\.?s\.?c?|b\.?a\.?|m\.?b\.?a\.?|bachelor|master|phd|university|institute|faculty|undergraduate|student|graduate|tsu|gtu|btu|freeuni|ilia|ბაკალავრ|მაგისტრ|უნივერსიტეტ|სტუდენტ)\b",
                    clean_line,
                    re.I,
                )
            )
            if looks_like_edu and len(clean_line) >= 5 and not re.fullmatch(r"[-*_•–—.\s]+", clean_line):
                yr_m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", clean_line)
                grad_year = int(yr_m.group(1)) if yr_m else None
                parts_e = [p.strip() for p in re.split(r"[|•@—–-]", clean_line, maxsplit=2) if p.strip()]
                degree = parts_e[0] if parts_e else clean_line
                institution = parts_e[1] if len(parts_e) > 1 else ""
                field_study = parts_e[2] if len(parts_e) > 2 else degree
                is_recent = bool(
                    re.search(r"\b(?:student|present|expected|202[4-9]|სტუდენტ)\b", clean_line, re.I)
                    or (grad_year is not None and grad_year >= 2022)
                )
                education_entries.append({
                    "degree": degree[:120],
                    "field_of_study": field_study[:120],
                    "institution": institution[:120],
                    "graduation_year": grad_year,
                    "is_student_or_recent_grad": is_recent,
                })

        exp_years = float(taxonomy_dict.get("years_of_experience") or 1.5)
        max_allowed_years = min(exp_years + 0.5, 2.0) if exp_years <= 2.0 else round(exp_years + 0.5, 1)
        seniority_level = taxonomy_dict.get("seniority_level") or ("JUNIOR" if exp_years <= 2.0 else "MID")
        verified_skills = list(taxonomy_dict.get("all_skills") or [])
        eligible_internships = bool(
            exp_years <= 2.5
            or courses_certs
            or any(e.get("is_student_or_recent_grad") for e in education_entries)
            or len(education_entries) > 0
        )
        internship_tracks: List[str] = []
        if eligible_internships:
            internship_tracks = list(dict.fromkeys(
                [f"{primary_role} Intern", f"Junior {primary_role.split()[0]} Trainee"]
                + [f"{e.get('field_of_study', '')} Graduate Intern".strip() for e in education_entries[:2] if e.get("field_of_study")]
            ))

        # Live Gemini 2.5 Flash structured extraction with Pydantic schema if key is configured
        if self.client:
            try:
                from google.genai import types
                prompt = f"""Extract the candidate profile, education, coursework, and universal domain-agnostic taxonomy from the following markdown.
CRITICAL INSTRUCTIONS:
- Works for ANY profession (IT/QA, Logistics, Supply Chain, Finance, Accounting, Marketing, Sales, HR, Legal, Public Admin, Hospitality, Healthcare, Engineering).
- `detected_industry`: Human-readable industry (e.g. "Supply Chain & Logistics", "Finance & Accounting", "IT & Software QA").
- `primary_role`: Candidate's exact primary target role.
- `adjacent_roles`: Top 3-4 optimal adjacent/transferable roles where their skills transfer seamlessly.
- `verified_skills`: All concrete tools, software, methodologies, and domain skills.
- `parsed_skills.education`: List of education objects with `degree`, `field_of_study`, `institution`, `graduation_year` (int or null), `is_student_or_recent_grad` (bool).
- `parsed_skills.courses_and_certifications`: List of completed bootcamps, courses, and certificates.
- `eligible_internships`: True if candidate is a student, recent grad, completed courses/bootcamps, or has <= 2.5 yrs experience.
- `internship_tracks`: Specific internship / graduate trainee tracks suited to their degree + courses + skills.
- `experience_years`: Exact numeric years from profile (never inflate unless stated).
- `max_allowed_years`: Strictly min(experience_years + 0.5, 2.0) when experience_years <= 2.0.
- `seniority_level`: Must be "JUNIOR", "MID", "SENIOR", or "LEAD".

Markdown:
{text[:4500]}
"""
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ParsedCandidateProfileSchema,
                        temperature=0.0,
                    ),
                )
                if resp and resp.text:
                    gem_parsed = ParsedCandidateProfileSchema.model_validate_json(resp.text)
                    gem_parsed.max_allowed_years = min(float(gem_parsed.experience_years) + 0.5, 2.0) if gem_parsed.experience_years <= 2.0 else round(float(gem_parsed.experience_years) + 0.5, 1)
                    for k in ["qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops", "all_skills"]:
                        existing_list = getattr(gem_parsed.parsed_skills, k)
                        merged = list(dict.fromkeys(existing_list + taxonomy_dict.get(k, [])))
                        setattr(gem_parsed.parsed_skills, k, merged)
                    if not gem_parsed.parsed_skills.education and education_entries:
                        gem_parsed.parsed_skills.education = education_entries
                    if courses_certs:
                        gem_parsed.parsed_skills.courses_and_certifications = list(dict.fromkeys(gem_parsed.parsed_skills.courses_and_certifications + courses_certs))
                    if eligible_internships:
                        gem_parsed.eligible_internships = True
                    if not gem_parsed.internship_tracks and internship_tracks:
                        gem_parsed.internship_tracks = internship_tracks
                    gem_parsed.verified_skills = list(dict.fromkeys(gem_parsed.verified_skills + gem_parsed.parsed_skills.all_skills))
                    if not gem_parsed.adjacent_roles:
                        gem_parsed.adjacent_roles = adjacent_roles
                    return gem_parsed
            except Exception as e:
                logger.warning(f"Gemini structured schema extraction fallback: {e}")

        return ParsedCandidateProfileSchema(
            full_name=full_name,
            headline=headline,
            primary_role=primary_role,
            detected_industry=detected_industry,
            adjacent_roles=adjacent_roles,
            verified_skills=verified_skills,
            eligible_internships=eligible_internships,
            internship_tracks=internship_tracks,
            email=email,
            phone=phone,
            location=location,
            github_url=github_url,
            linkedin_url=linkedin_url,
            experience_years=exp_years,
            max_allowed_years=max_allowed_years,
            seniority_level=seniority_level,
            target_industry=target_industry,
            parsed_skills=ExtractedSkillsTaxonomy(
                qa_automation=taxonomy_dict.get("qa_automation", []),
                manual_qa=taxonomy_dict.get("manual_qa", []),
                languages=taxonomy_dict.get("languages", []),
                api_and_performance=taxonomy_dict.get("api_and_performance", []),
                cicd_and_devops=taxonomy_dict.get("cicd_and_devops", []),
                tools=taxonomy_dict.get("tools", []),
                frameworks=taxonomy_dict.get("frameworks", []),
                spoken_languages=taxonomy_dict.get("spoken_languages", ["English", "Georgian"]),
                achievements=achievements,
                education=education_entries,
                courses_and_certifications=courses_certs,
                all_skills=taxonomy_dict.get("all_skills", []),
            ),
        )

    def get_search_queries_for_profile(
        self,
        parsed_skills: Optional[Dict[str, Any]] = None,
        headline: str = "",
    ) -> Dict[str, Any]:
        """
        Delegates dynamic domain-agnostic query generation to scrapers/query_builder.py.
        """
        from .scrapers.query_builder import build_search_queries
        return build_search_queries(parsed_skills, headline=headline)

    def upsert_candidate_profile(self, raw_markdown: str, mark_uploaded: bool = True) -> CandidateProfile:
        """
        Extracts structured profile data from raw_markdown and upserts it into CandidateProfile in SQLite/PostgreSQL.
        All PII stays encrypted at rest in CandidateProfile; never writes plaintext markdown to disk.
        """
        init_db()

        extracted = self.extract_structured_profile(raw_markdown)
        skills_payload: Dict[str, Any] = extracted.parsed_skills.model_dump()
        skills_payload["years_of_experience"] = extracted.experience_years
        skills_payload["max_allowed_years"] = extracted.max_allowed_years
        skills_payload["seniority_level"] = extracted.seniority_level
        skills_payload["target_industry"] = extracted.target_industry
        skills_payload["detected_industry"] = extracted.detected_industry
        skills_payload["primary_role"] = extracted.primary_role
        skills_payload["adjacent_roles"] = extracted.adjacent_roles
        skills_payload["verified_skills"] = extracted.verified_skills or skills_payload.get("all_skills", [])
        skills_payload["eligible_internships"] = extracted.eligible_internships
        skills_payload["internship_tracks"] = extracted.internship_tracks
        skills_payload["headline"] = extracted.headline
        search_cfg = self.get_search_queries_for_profile(skills_payload, headline=extracted.headline)
        skills_payload["target_role"] = search_cfg["target_role"]
        skills_payload["search_queries"] = search_cfg
        skills_payload["user_uploaded"] = mark_uploaded

        with Session(engine, expire_on_commit=False) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()

            existing_vault: Dict[str, Any] = {}
            if profile and isinstance(profile.parsed_skills, dict):
                existing_vault = dict(profile.parsed_skills.get("ground_truth_vault") or {})
            elif GROUND_TRUTH_FILE.exists():
                try:
                    existing_vault = json.loads(GROUND_TRUTH_FILE.read_text(encoding="utf-8"))
                except Exception:
                    existing_vault = {}

            cand = existing_vault.setdefault("candidate", {})
            cand["full_name"] = extracted.full_name
            parts = extracted.full_name.split()
            cand["first_name"] = parts[0] if parts else "Candidate"
            cand["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
            cand["headline"] = extracted.headline
            cand["email"] = extracted.email
            cand["phone"] = extracted.phone
            cand.setdefault("links", {})["github"] = extracted.github_url
            cand.setdefault("links", {})["linkedin"] = extracted.linkedin_url
            cand.setdefault("compensation", {})["notice_period"] = "1 week after offer"
            existing_vault.setdefault("skills", {})["core"] = skills_payload.get("all_skills", [])

            skills_payload["ground_truth_vault"] = existing_vault

            if profile:
                profile.raw_markdown = raw_markdown
                profile.full_name = extracted.full_name
                profile.email = extracted.email
                profile.phone = extracted.phone
                profile.location = extracted.location
                profile.github_url = extracted.github_url
                profile.linkedin_url = extracted.linkedin_url
                profile.parsed_skills = skills_payload
                profile.experience_years = extracted.experience_years
                profile.updated_at = utc_now()
            else:
                profile = CandidateProfile(
                    raw_markdown=raw_markdown,
                    full_name=extracted.full_name,
                    email=extracted.email,
                    phone=extracted.phone,
                    location=extracted.location,
                    github_url=extracted.github_url,
                    linkedin_url=extracted.linkedin_url,
                    parsed_skills=skills_payload,
                    experience_years=extracted.experience_years,
                    updated_at=utc_now(),
                )

            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile


profile_service = ProfileService()
