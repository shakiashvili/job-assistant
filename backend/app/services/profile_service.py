import json
import logging
import re
from typing import Dict, Any, List
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
    full_name: str = "Alex Mercer"
    headline: str = "Senior QA Automation Engineer & SDET"
    email: str = "alex.mercer.dev@gmail.com"
    phone: str = "+49 152 98765432"
    location: str = "Berlin / Tbilisi (Remote)"
    github_url: str = "https://github.com/alex-mercer-automation"
    linkedin_url: str = "https://linkedin.com/in/alex-mercer-qa"
    experience_years: float = 5.0
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

        # Deterministic extraction baseline
        taxonomy_dict = matcher_service.parse_skills_markdown(text)
        full_name = "Alex Mercer"
        headline = "Senior QA Automation Engineer & SDET"
        email = "alex.mercer.dev@gmail.com"
        phone = "+49 152 98765432"
        location = "Berlin / Tbilisi (Remote)"
        github_url = "https://github.com/alex-mercer-automation"
        linkedin_url = "https://linkedin.com/in/alex-mercer-qa"

        for line in text.splitlines():
            s = line.strip()
            if s.startswith("# "):
                parts = re.split(r"\s+[—–-]\s+", s[2:].strip(), maxsplit=1)
                if parts[0]:
                    full_name = parts[0].strip()
                if len(parts) > 1:
                    headline = parts[1].strip()
                break

        name_m = re.search(r"(?:Full Name|სახელი და გვარი|Name)\**\s*:\**\s*([^\n]+)", text, re.I)
        if name_m:
            full_name = name_m.group(1).strip()

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

        # Live Gemini 2.5 Flash structured extraction with Pydantic schema if key is configured
        if self.client:
            try:
                from google.genai import types
                prompt = f"""Extract the candidate profile and technical QA/SDET taxonomy from the following markdown.
Strictly ground all extracted fields in the provided text without inventing skills or metrics.

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
            experience_years=float(taxonomy_dict.get("years_of_experience", 5.0)),
            parsed_skills=ExtractedSkillsTaxonomy(
                qa_automation=taxonomy_dict.get("qa_automation", []),
                manual_qa=taxonomy_dict.get("manual_qa", []),
                languages=taxonomy_dict.get("languages", []),
                api_and_performance=taxonomy_dict.get("api_and_performance", []),
                cicd_and_devops=taxonomy_dict.get("cicd_and_devops", []),
                tools=taxonomy_dict.get("tools", []),
                frameworks=taxonomy_dict.get("frameworks", []),
                spoken_languages=taxonomy_dict.get("spoken_languages", ["English"]),
                achievements=achievements,
                all_skills=taxonomy_dict.get("all_skills", []),
            ),
        )

    def upsert_candidate_profile(self, raw_markdown: str) -> CandidateProfile:
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
            cand["first_name"] = parts[0] if parts else "Alex"
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
