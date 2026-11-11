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
    all_skills: List[str] = Field(default_factory=list)


class ParsedCandidateProfileSchema(BaseModel):
    full_name: str = "Candidate"
    headline: str = "QA Engineer"
    email: str = "candidate@example.com"
    phone: str = "+000 000 0000"
    location: str = "Tbilisi, Georgia (Remote / Abroad)"
    github_url: str = "https://github.com/example-candidate"
    linkedin_url: str = "https://linkedin.com/in/example-candidate"
    experience_years: float = 1.5
    seniority_level: str = "JUNIOR"
    target_industry: str = "qa_tech"
    parsed_skills: ExtractedSkillsTaxonomy = Field(default_factory=ExtractedSkillsTaxonomy)


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

        # 2. Industry & Headline extraction
        if any(w in lower_text for w in ["receptionist", "hotel", "opera pms", "fidelio", "hospitality", "guest relations", "მიმღები"]):
            target_industry = "receptionist_hospitality"
            headline = "Front Desk Receptionist & Hospitality Specialist"
        elif any(w in lower_text for w in ["patient coordinator", "medical receptionist", "hospital", "clinic", "ehr", "emr", "სამედიცინო"]):
            target_industry = "healthcare_hospital"
            headline = "Hospital Patient Coordinator & Medical Receptionist"
        elif any(w in lower_text for w in ["customer service", "client care", "zendesk", "intercom", "omnichannel support", "მომხმარებელთა მხარდაჭერა"]):
            target_industry = "customer_service"
            headline = "Customer Service & Client Care Specialist"
        else:
            target_industry = "qa_tech"
            if any(w in lower_text for w in ["portfolio project", "entry-level", "starter", "junior", "1.5"]):
                headline = "QA Engineer (Test Design & API Quality)"
            else:
                headline = "QA Automation Engineer"

        # Check explicit headline in markdown
        headline_m = re.search(r"(?:Headline|Target Role|პოზიცია|როლი)\**\s*:\**\s*([^\n]+)", text, re.I)
        if headline_m:
            headline = headline_m.group(1).strip()

        email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_m:
            email = email_m.group(0)

        phone_m = re.search(r"(?:Phone|ტელეფონი|Tel)\**\s*:\**\s*([+\d\s()-]{7,22})", text, re.I)
        if phone_m:
            phone = phone_m.group(1).strip()

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
        for line in text.splitlines():
            s = line.strip()
            if s.startswith(("- ", "* ")) and any(ch.isdigit() for ch in s):
                achievements.append(re.sub(r"^[-*]\s*", "", s))

        exp_years = float(taxonomy_dict.get("years_of_experience") or 1.5)
        seniority_level = taxonomy_dict.get("seniority_level") or ("JUNIOR" if exp_years <= 2.5 else "MID")

        # Live Gemini 2.5 Flash structured extraction with Pydantic schema if key is configured
        if self.client:
            try:
                from google.genai import types
                prompt = f"""Extract the candidate profile and technical/domain taxonomy from the following markdown.
CRITICAL INSTRUCTIONS:
- Candidate full_name: Look for Author, Name, or candidate bio. Do NOT use document or project titles (such as "KLIPY Sticker Search API") as the candidate's name.
- Experience years: Ground accurately. If the document describes a starter portfolio project, entry-level, or 1.5 years experience, reflect that (e.g. 1.5 years). Never hallucinate 5+ years or Senior level unless explicitly stated.
- Seniority level: Must be "JUNIOR", "MID", "SENIOR", or "LEAD".
- Target industry: One of "qa_tech", "receptionist_hospitality", "customer_service", "healthcare_hospital".

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
                    # Merge deterministic taxonomy items so nothing is missed
                    for k in ["qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops", "all_skills"]:
                        existing_list = getattr(gem_parsed.parsed_skills, k)
                        merged = list(dict.fromkeys(existing_list + taxonomy_dict.get(k, [])))
                        setattr(gem_parsed.parsed_skills, k, merged)
                    return gem_parsed
            except Exception as e:
                logger.warning(f"Gemini structured schema extraction fallback: {e}")

        return ParsedCandidateProfileSchema(
            full_name=full_name,
            headline=headline,
            email=email,
            phone=phone,
            location=location,
            github_url=github_url,
            linkedin_url=linkedin_url,
            experience_years=exp_years,
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
                all_skills=taxonomy_dict.get("all_skills", []),
            ),
        )

    def get_search_queries_for_profile(
        self,
        parsed_skills: Optional[Dict[str, Any]] = None,
        headline: str = "",
    ) -> Dict[str, Any]:
        """
        Determines portal-specific role search parameters directly from CandidateProfile
        so scrapers dynamically search by the candidate's target role (e.g., QA / Software Tester).
        """
        skills = parsed_skills or {}
        target_industry = str(skills.get("target_industry") or "qa_tech").lower()
        hl = str(headline or skills.get("headline") or "").lower()
        has_qa_skills = bool(skills.get("qa_automation") or skills.get("manual_qa")) or any(
            w in hl for w in ["qa", "test", "sdet", "quality"]
        )

        if target_industry == "receptionist_hospitality" or any(
            w in hl for w in ["receptionist", "hospitality", "hotel", "front desk"]
        ):
            return {
                "target_role": "Receptionist",
                "search_terms": ["Receptionist", "Hospitality", "მიმღები", "ადმინისტრატორი"],
                "jobs_ge_urls": [
                    "https://jobs.ge/ge/?page=1&q=Receptionist",
                    "https://jobs.ge/ge/?page=1&q=%E1%83%9B%E1%83%98%E1%83%9B%E1%83%A6%E1%83%94%E1%83%91%E1%83%98",
                ],
                "djinni_url": None,
                "dou_url": None,
                "hr_ge_url": "https://www.hr.ge/search-posting?q=receptionist",
                "domain_keywords": [
                    "receptionist", "front desk", "hospitality", "concierge", "hotel", "guest",
                    "მიმღები", "რეცეფციონისტი", "სასტუმრო", "ადმინისტრატორი",
                ],
            }

        if target_industry == "healthcare_hospital" or any(
            w in hl for w in ["medical", "hospital", "clinic", "patient coordinator"]
        ):
            return {
                "target_role": "Medical Coordinator",
                "search_terms": ["Medical", "Clinic", "სამედიცინო"],
                "jobs_ge_urls": [
                    "https://jobs.ge/ge/?page=1&q=%E1%83%A1%E1%83%90%E1%83%9B%E1%83%94%E1%83%93%E1%83%98%E1%83%AA%E1%83%98%E1%83%9C%E1%83%9D",
                    "https://jobs.ge/ge/?page=1&q=Medical",
                ],
                "djinni_url": None,
                "dou_url": None,
                "hr_ge_url": "https://www.hr.ge/search-posting?q=medical",
                "domain_keywords": [
                    "medical", "hospital", "clinic", "patient", "coordinator",
                    "სამედიცინო", "კლინიკა", "პაციენტ", "რეგისტრატორი",
                ],
            }

        if target_industry == "customer_service" or any(
            w in hl for w in ["customer service", "support specialist", "client care", "call center"]
        ):
            return {
                "target_role": "Customer Support",
                "search_terms": ["Support", "Customer Service", "მხარდაჭერა"],
                "jobs_ge_urls": [
                    "https://jobs.ge/ge/?page=1&q=Support",
                    "https://jobs.ge/ge/?page=1&q=Customer",
                ],
                "djinni_url": "https://djinni.co/jobs/?primary_keyword=Support&employment=remote",
                "dou_url": "https://jobs.dou.ua/vacancies/?category=Support&remote",
                "hr_ge_url": "https://www.hr.ge/search-posting?q=support",
                "domain_keywords": [
                    "support", "customer service", "client care", "call center", "helpdesk",
                    "მხარდაჭერა", "ოპერატორი", "ქოლ",
                ],
            }

        # Default: QA / Software Testing profile
        role_label = "QA" if has_qa_skills else "QA"
        return {
            "target_role": role_label,
            "search_terms": ["QA", "Tester", "Software Tester"],
            "jobs_ge_urls": [
                "https://jobs.ge/ge/?page=1&q=QA&cid=6",
                "https://jobs.ge/ge/?page=1&q=Tester&cid=6",
            ],
            "djinni_url": "https://djinni.co/jobs/?primary_keyword=QA&employment=remote",
            "dou_url": "https://jobs.dou.ua/vacancies/?category=QA&remote",
            "hr_ge_url": "https://www.hr.ge/search-posting?q=QA",
            "domain_keywords": [
                "qa", "quality assurance", "tester", "test engineer", "sdet",
                "manual qa", "automation", "playwright", "cypress", "selenium", "ტესტ",
            ],
        }

    def upsert_candidate_profile(self, raw_markdown: str, mark_uploaded: bool = True) -> CandidateProfile:
        """
        Extracts structured profile data from raw_markdown and upserts it into CandidateProfile in SQLite/PostgreSQL.
        """
        init_db()
        try:
            SKILLS_MD_FILE.write_text(raw_markdown, encoding="utf-8")
        except Exception:
            pass

        extracted = self.extract_structured_profile(raw_markdown)
        skills_payload: Dict[str, Any] = extracted.parsed_skills.model_dump()
        skills_payload["years_of_experience"] = extracted.experience_years
        skills_payload["seniority_level"] = extracted.seniority_level
        skills_payload["target_industry"] = extracted.target_industry
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
