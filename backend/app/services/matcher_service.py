import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from .gemini_service import MULTI_INDUSTRY_SKILLS

logger = logging.getLogger(__name__)

QA_TAXONOMY_CATALOG: Dict[str, List[str]] = {
    "qa_automation": [
        "Playwright", "Selenium", "Selenium WebDriver", "Cypress", "Appium",
        "PyTest", "JUnit", "TestNG", "Jest", "WebdriverIO", "Robot Framework"
    ],
    "manual_qa": [
        "Manual Testing", "Exploratory Testing", "Test Plans", "Test Cases",
        "Bug Reporting", "Regression Testing", "UAT", "BDD", "Cucumber", "Gherkin",
        "Jira", "Xray", "TestRail"
    ],
    "languages": [
        "Python", "TypeScript", "JavaScript", "Java", "C#", "SQL", "Bash", "Go"
    ],
    "api_and_performance": [
        "Postman", "REST Assured", "REST API", "GraphQL", "Swagger", "OpenAPI",
        "k6", "JMeter", "Locust", "Gatling", "SoapUI"
    ],
    "cicd_and_devops": [
        "GitHub Actions", "GitLab CI", "Jenkins", "Docker", "Kubernetes",
        "AWS", "GCP", "Azure", "Linux", "Git"
    ],
}

CANONICAL_SKILL_NAMES: Dict[str, str] = {
    "playwright": "Playwright",
    "selenium": "Selenium",
    "selenium webdriver": "Selenium WebDriver",
    "cypress": "Cypress",
    "appium": "Appium",
    "pytest": "PyTest",
    "junit": "JUnit",
    "testng": "TestNG",
    "jest": "Jest",
    "webdriverio": "WebdriverIO",
    "robot framework": "Robot Framework",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "python": "Python",
    "java": "Java",
    "c#": "C#",
    "sql": "SQL",
    "bash": "Bash",
    "go": "Go",
    "postman": "Postman",
    "rest assured": "REST Assured",
    "rest api": "REST API",
    "graphql": "GraphQL",
    "swagger": "Swagger",
    "openapi": "OpenAPI",
    "k6": "k6",
    "jmeter": "JMeter",
    "locust": "Locust",
    "gatling": "Gatling",
    "soapui": "SoapUI",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "ci/cd": "CI/CD",
    "jenkins": "Jenkins",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "linux": "Linux",
    "git": "Git",
    "ai tools": "AI Tools",
    "ai-assisted testing": "AI-Assisted Testing",
    "llm evaluation": "LLM Evaluation",
    "prompt engineering": "Prompt Engineering",
    "gemini": "Gemini",
    "chatgpt": "ChatGPT",
    "github copilot": "GitHub Copilot",
    "jira": "Jira",
    "xray": "Xray",
    "testrail": "TestRail",
    "uat": "UAT",
    "bdd": "BDD",
    "api": "API",
    "html": "HTML",
    "css": "CSS",
    "json": "JSON",
    "xml": "XML",
    "chrome devtools": "Chrome DevTools",
    "devtools": "Chrome DevTools",
}

_DATE_OR_PROSE_RE = re.compile(
    r"\b(?:19\d{2}|20\d{2}|january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
    r"present|current|tbilisi|batumi|kutaisi|georgia|remote|hybrid|onsite)\b",
    re.I,
)
_PROSE_START_RE = re.compile(
    r"^(?:and|or|the|a|an|in|on|at|to|for|with|from|by|of|as|"
    r"conducted|tested|verifying|verified|built|created|maintained|executed|"
    r"designed|reported|documented|collaborated|participated|managed|assisted|supported)\b",
    re.I,
)


def _clean_skill_token(raw: str) -> str:
    s = re.sub(r"[*_`~]+", "", raw or "").strip()
    s = s.strip("•·–—-.,:;()[]{}").strip()
    if not s or len(s) < 2 or len(s) > 36:
        return ""
    if "@" in s or "http" in s.lower() or "://" in s or "•" in raw:
        return ""
    if _DATE_OR_PROSE_RE.search(s) or _PROSE_START_RE.search(s):
        return ""
    # Reject full sentence fragments (> 4 words or trailing period in original)
    if len(s.split()) > 4 or raw.strip().endswith("."):
        return ""
    lower = s.lower()
    if lower in CANONICAL_SKILL_NAMES:
        return CANONICAL_SKILL_NAMES[lower]
    return s


def dedupe_skills_case_insensitive(items: List[str]) -> List[str]:
    """Deduplicates skills preserving canonical technical casing."""
    seen: Dict[str, str] = {}
    ordered_keys: List[str] = []
    for item in items:
        cleaned = _clean_skill_token(item) if item else ""
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen[key] = CANONICAL_SKILL_NAMES.get(key, cleaned)
            ordered_keys.append(key)
    return [seen[k] for k in ordered_keys]


class MatcherService:
    """
    1. Parses uploaded skills.md into structured QA/SDET + Multi-Industry JSON taxonomy
       for CandidateProfile persistence.
    2. Evaluates scraped JobPosting records against CandidateProfile, computing suitability_score (0-100),
       missing technical requirements, and match_rationale.
    3. Automatically promotes listings with suitability_score >= 75% to the "STAGED"
       ("Ready to Apply / Staging") queue.
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
                logger.warning(f"MatcherService Gemini init fallback: {e}")

    def parse_skills_markdown(self, raw_markdown: str) -> Dict[str, Any]:
        """
        Parses raw_markdown (from skills.md) into structured taxonomy for CandidateProfile.parsed_skills.
        Uses Gemini 2.5 Flash if available, enriched with deterministic taxonomy matching.
        """
        text = raw_markdown or ""
        lower_text = text.lower()

        taxonomy: Dict[str, Any] = {
            "qa_automation": [],
            "manual_qa": [],
            "languages": [],
            "api_and_performance": [],
            "cicd_and_devops": [],
            "tools": [],
            "frameworks": [],
            "spoken_languages": [],
            "years_of_experience": 1.5,
            "seniority_level": "JUNIOR",
            "all_skills": [],
        }

        # Extract years of experience (e.g., "1.5 years", "1-2 years", "5+ years", "4 years")
        yr_match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წელი|წლიანი)", lower_text)
        if yr_match:
            taxonomy["years_of_experience"] = float(yr_match.group(1))
        elif any(w in lower_text for w in ["portfolio project", "entry-level", "junior", "intern", "დამწყები"]):
            taxonomy["years_of_experience"] = 1.5

        # Infer seniority level from years
        exp = taxonomy["years_of_experience"]
        if exp <= 2.5:
            taxonomy["seniority_level"] = "JUNIOR"
        elif exp <= 5.0:
            taxonomy["seniority_level"] = "MID"
        elif exp <= 8.0:
            taxonomy["seniority_level"] = "SENIOR"
        else:
            taxonomy["seniority_level"] = "LEAD"

        # Match QA/SDET taxonomy categories
        for category, items in QA_TAXONOMY_CATALOG.items():
            matched = []
            for skill in items:
                pattern = r"\b" + re.escape(skill.lower()) + r"\b"
                if skill.lower() in ("c#", "k6"):
                    if skill.lower() in lower_text:
                        matched.append(skill)
                elif re.search(pattern, lower_text):
                    matched.append(skill)
            taxonomy[category] = matched

        # Spoken languages
        lang_aliases = [
            ("English", ("english", "ინგლისური")),
            ("Georgian", ("georgian", "ქართული")),
            ("German", ("german", "გერმანული", "deutsch")),
            ("Ukrainian", ("ukrainian", "українська", "украинский", "უკრაინული")),
            ("Russian", ("russian", "русский", "რუსული")),
            ("Polish", ("polish", "polski", "польский", "პოლონური")),
            ("Spanish", ("spanish", "ესპანური")),
            ("French", ("french", "ფრანგული")),
        ]
        for canon_lang, patterns in lang_aliases:
            if any(p in lower_text for p in patterns):
                if canon_lang not in taxonomy["spoken_languages"]:
                    taxonomy["spoken_languages"].append(canon_lang)
        if not taxonomy["spoken_languages"]:
            taxonomy["spoken_languages"] = ["English", "Georgian"]

        # Multi-industry & general skills
        all_skills: List[str] = []
        for cat_list in [
            taxonomy["qa_automation"],
            taxonomy["manual_qa"],
            taxonomy["languages"],
            taxonomy["api_and_performance"],
            taxonomy["cicd_and_devops"],
        ]:
            for s in cat_list:
                if s not in all_skills:
                    all_skills.append(s)

        for ind_skills in MULTI_INDUSTRY_SKILLS.values():
            for skill_kw in ind_skills:
                low_kw = skill_kw.lower()
                if low_kw in CANONICAL_SKILL_NAMES:
                    canonical = CANONICAL_SKILL_NAMES[low_kw]
                else:
                    canonical = skill_kw.upper() if len(skill_kw) <= 3 else skill_kw.title()
                pat = r"\b" + re.escape(low_kw) + r"\b" if low_kw not in ("c#", "k6") else re.escape(low_kw)
                if (low_kw in lower_text if low_kw in ("c#", "k6") else re.search(pat, lower_text)):
                    if all(existing.lower() != canonical.lower() for existing in all_skills):
                        all_skills.append(canonical)

        # Extract bullet items strictly under dedicated ## Skills headings (stop before ### roles or Experience)
        in_skills = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("## "):
                header_l = s.lower()
                is_exp_header = any(w in header_l for w in ["experience", "history", "work", "project", "education", "გამოცდილება"])
                in_skills = (not is_exp_header) and any(
                    w in header_l for w in ["skill", "stack", "tech", "უნარ", "კომპეტენც"]
                )
                continue
            if s.startswith("### ") or (s.startswith("# ") and not s.startswith("## ")):
                in_skills = False
                continue
            if in_skills and s.startswith(("-", "*")):
                # Stop collecting as skills if bullet looks like a company/date sub-header
                if _DATE_OR_PROSE_RE.search(s):
                    continue
                cleaned = re.sub(r"^[-*]\s*(?:\*\*[^*]+?\*\*:?)?\s*", "", s)
                for part in re.split(r"[,;/|]", cleaned):
                    token = _clean_skill_token(part)
                    if token and all(existing.lower() != token.lower() for existing in all_skills):
                        all_skills.append(token)

        all_skills = dedupe_skills_case_insensitive(all_skills)
        taxonomy["frameworks"] = dedupe_skills_case_insensitive(taxonomy["qa_automation"] + ["PyTest", "Playwright", "Cypress"])
        taxonomy["tools"] = dedupe_skills_case_insensitive(taxonomy["api_and_performance"] + taxonomy["cicd_and_devops"] + ["Jira", "Git"])
        taxonomy["all_skills"] = all_skills

        # Optionally enrich via Gemini 2.5 Flash if live key is present
        if self.client:
            try:
                from google.genai import types
                prompt = f"""Parse this candidate skills markdown into a JSON object with keys:
- qa_automation (list of strings)
- manual_qa (list of strings)
- languages (list of programming languages)
- api_and_performance (list of API/performance testing tools)
- cicd_and_devops (list of CI/CD & DevOps tools)
- years_of_experience (number)

Markdown:
{text[:3000]}
"""
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                if resp and resp.text:
                    gem_data = json.loads(resp.text)
                    for k in ["qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops"]:
                        if isinstance(gem_data.get(k), list):
                            merged = list(dict.fromkeys(taxonomy[k] + [str(x) for x in gem_data[k]]))
                            taxonomy[k] = merged
            except Exception as e:
                logger.warning(f"Gemini skills taxonomy enrichment fallback: {e}")

        return taxonomy

    SPECIALIZED_PLATFORMS = [
        "Salesforce", "WordPress", "Shopify", "SAP", "Game Testing",
        "Gamedev", "Unity", "iGaming", "Swift", "Kotlin", "Ruby", "PHP"
    ]

    def extract_job_requirements(self, title: str, description: str) -> List[str]:
        """Extracts actual required technical and domain skills from job title + description without fabrication."""
        combined = f"{title}\n{description}".lower()
        required: List[str] = []

        for category, items in QA_TAXONOMY_CATALOG.items():
            for skill in items:
                if skill == "Selenium WebDriver":
                    continue
                pattern = r"\b" + re.escape(skill.lower()) + r"\b"
                if skill.lower() in ("c#", "k6"):
                    if skill.lower() in combined and skill not in required:
                        required.append(skill)
                elif re.search(pattern, combined) and skill not in required:
                    required.append(skill)

        for spec in self.SPECIALIZED_PLATFORMS:
            if re.search(r"\b" + re.escape(spec.lower()) + r"\b", combined) and spec not in required:
                required.append(spec)

        # Recognize Georgian QA terminology accurately
        if any(w in combined for w in ["ავტომატიზაც", "automation code", "test automation", "qa automation"]):
            if "QA Automation" not in required:
                required.append("QA Automation")
        if any(w in combined for w in ["მანუალ", "manual qa", "manual testing"]):
            if "Manual Testing" not in required:
                required.append("Manual Testing")

        for ind_skills in MULTI_INDUSTRY_SKILLS.values():
            for skill_kw in ind_skills:
                low_kw = skill_kw.lower()
                canonical = CANONICAL_SKILL_NAMES.get(low_kw, skill_kw.title() if len(skill_kw) > 3 else skill_kw.upper())
                pat = r"\b" + re.escape(low_kw) + r"\b" if low_kw not in ("c#", "k6") else re.escape(low_kw)
                if (low_kw in combined if low_kw in ("c#", "k6") else re.search(pat, combined)):
                    if all(r.lower() != canonical.lower() for r in required):
                        required.append(canonical)

        return required

    def validate_seniority_gate(
        self,
        candidate_years: float,
        candidate_seniority: str,
        job_title: str,
        job_description: str,
        max_allowed_years: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Strict 2.0-Year Experience Guard:
        - When candidate_years <= 2.0: max_allowed_years = min(candidate_years + 0.5, 2.0) (HARD CAP at 2.0 years).
        - Disqualifies Senior, Lead, Principal, Head of, Staff, Director, Architect, Chief, Middle+, Mid+, უფროსი, მთავარი, წამყვანი.
        - Disqualifies jobs requiring > max_allowed_years (including upper range e.g. '2-3 years').
        - Allows Intern, Trainee, Junior, and Junior-Mid (0 to 2.0 years).
        """
        combined = f"{job_title}\n{job_description}".lower()
        title_lower = (job_title or "").lower()

        exec_titles = [
            "lead", "principal", "head of", "staff", "director", "architect", "chief", "vp",
            "middle+", "mid+", "mid/senior", "middle/senior",
            "ლიდი", "ხელმძღვანელი", "დირექტორი", "მთავარი", "წამყვანი",
        ]
        senior_titles = ["senior", "sr.", "sr ", "უფროსი", "სინიორ"]
        tech_manager_titles = ["qa manager", "engineering manager", "test manager", "it manager"]

        # Extract all experience requirement signals (ranges e.g. "2-3 years", "3-5 years", "3+ years", "მინიმუმ 3 წელი", "від 3 років")
        found_years: List[float] = []

        # 1. Range format (e.g. "2-3 years", "3-5 წელი", "2–4 роки")
        for rm in re.finditer(r"(\d+(?:\.\d+)?)\s*[–\-]\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|років|лет)", combined):
            try:
                found_years.append(float(rm.group(2)))
            except Exception:
                pass

        # 2. Minimum / at least format (e.g. "მინიმუმ 3 წელი", "at least 3 years", "სულ მცირე 3 წელი", "досвід від 3 років")
        for mm in re.finditer(r"(?:მინიმუმ|სულ\s+მცირე|არანაკლებ|at least|minimum of|minimum|min\.?|від|от)\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|рок(?:ів)?|лет|года)?", combined):
            try:
                found_years.append(float(mm.group(1)))
            except Exception:
                pass

        # 3. Direct years of experience (e.g. "3+ years of experience", "3 წლიანი გამოცდილება")
        for ym in re.finditer(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|роკ(?:ів)?|лет|года)(?:\s+of)?\s*(?:experience|გამოცდილება|досвід|опыт)?", combined):
            try:
                found_years.append(float(ym.group(1)))
            except Exception:
                pass

        # 4. Keyed requirements (e.g. "Experience: 3 years", "გამოცდილება: 3 წელი")
        for em in re.finditer(r"(?:experience|გამოცდილება|досвід|опыт)\s*[:\-–]\s*(\d+(?:\.\d+)?)", combined):
            try:
                found_years.append(float(em.group(1)))
            except Exception:
                pass

        # Filter out calendar years (2020+) and extreme values, keeping legitimate professional experience requirements
        valid_exp = [y for y in found_years if 0.5 <= y <= 15.0]
        job_req_years = max(valid_exp) if valid_exp else None

        # Direct regex guard for 3+ years (with negative lookbehind to avoid matching decimals like 1.5 yrs as 5 yrs)
        has_3_plus_guard = bool(
            re.search(r"(?<![\d.])(?:[3-9]|\d{2,})(?:\.\d+)?\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|років|лет)\b", combined)
            or re.search(r"(?:მინიმუმ|სულ\s+მცირე|არანაკლებ|at least|minimum of|від|от)\s*[:\-–]?\s*(?<![\d.])(?:[3-9]|\d{2,})(?:\.\d+)?", combined)
        )

        cap = max_allowed_years if max_allowed_years is not None else (
            min(candidate_years + 0.5, 2.0) if candidate_years <= 2.0 else round(candidate_years + 1.0, 1)
        )

        # Gate 1: Strict <= 2.0-2.5 yrs Junior/Junior-Mid Guard
        if candidate_years <= 2.5:
            for s in exec_titles + senior_titles + tech_manager_titles:
                if s in ("middle+", "mid+", "sr."):
                    matched_s = s in title_lower
                else:
                    matched_s = bool(re.search(r"\b" + re.escape(s) + r"\b", title_lower))
                if matched_s:
                    return (
                        False,
                        f"Disqualified by Seniority Gate: Role requires {s.title()}, exceeding candidate cap ({cap:.1f} yrs max).",
                    )
            if cap <= 2.0 and has_3_plus_guard:
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires 3+ years experience (strictly capped at {cap:.1f} yrs).",
                )
            if job_req_years is not None and job_req_years > cap:
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires {job_req_years:g} yrs exp (strictly capped at {cap:.1f} yrs).",
                )
            duty_leadership_signals = [
                "manage a team of",
                "lead a team of",
                "architect enterprise",
                "define company-wide strategy",
                "full p&l ownership",
                "direct report to the ceo",
                "budget ownership across",
            ]
            hit_duty = next((d for d in duty_leadership_signals if d in combined), None)
            if hit_duty:
                return (
                    False,
                    f"Disqualified by Duty Gate: Job expects senior/management responsibility ('{hit_duty}') above {cap:.1f} yr cap.",
                )

        # Gate 2: Mid level (2.5 to 5.0 years)
        elif candidate_years <= 5.0:
            for s in exec_titles:
                if s in title_lower:
                    return (
                        False,
                        f"Disqualified by Seniority Gate: Role requires executive/lead {s.title()}, but candidate is Mid-level ({candidate_years:.1f} yrs exp).",
                    )
            if job_req_years is not None and job_req_years > (candidate_years + 2.5):
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires {job_req_years:g}+ years exp, exceeding candidate's {candidate_years:.1f} yrs.",
                )

        return (True, "Seniority and experience requirements satisfied.")

    def validate_domain_gate(
        self,
        parsed_skills: Dict[str, Any],
        job_title: str,
        job_description: str,
        portal: str = "custom",
    ) -> Tuple[bool, str]:
        """Backwards-compatible wrapper around universal domain-agnostic alignment classifier."""
        tier, reason = self.classify_domain_alignment(parsed_skills, job_title, job_description, portal=portal)
        return (tier != "NONE", reason)

    def classify_domain_alignment(
        self,
        parsed_skills: Dict[str, Any],
        job_title: str,
        job_description: str,
        portal: str = "custom",
        candidate_skills: Optional[List[str]] = None,
        required_skills: Optional[List[str]] = None,
    ) -> Tuple[str, str]:
        """
        Universal Domain-Agnostic Alignment Classifier:
        Returns (tier_hint, aligned_role_or_reason) where tier_hint is:
        - "DIRECT" -> directly matches candidate's primary role/industry
        - "ADJACENT" -> transferable skills overlap with an optimal adjacent role (e.g., QA SQL/Postman -> Technical Support)
        - "PUBLIC_INTERNSHIP" -> vacancy.hr.gov.ge public administration / entry internship
        - "NONE" -> off-domain mismatch
        """
        title_lower = (job_title or "").lower()
        combined = f"{job_title}\n{job_description}".lower()
        target_industry = str(parsed_skills.get("target_industry") or "qa_tech").lower()
        search_q = parsed_skills.get("search_queries") or {}
        primary_role = str(parsed_skills.get("primary_role") or parsed_skills.get("headline") or "").lower()
        adjacent_roles = [str(r) for r in (parsed_skills.get("adjacent_roles") or []) if r]

        # Build direct domain signals from search_queries + primary_role tokens + catalog
        direct_signals = [str(s).lower() for s in (search_q.get("domain_keywords") or []) if len(str(s)) >= 2]
        if target_industry == "qa_tech" and not direct_signals:
            direct_signals = ["qa", "quality assurance", "quality engineer", "test", "tester", "sdet", "automation", "ტესტ", "ხარისხ"]
        elif target_industry == "receptionist_hospitality" and not direct_signals:
            direct_signals = ["reception", "front desk", "hospitality", "concierge", "hotel", "guest", "მიმღებ", "რეცეფც", "სასტუმრ", "ადმინისტრატორ"]
        elif target_industry == "healthcare_hospital" and not direct_signals:
            direct_signals = ["medical", "hospital", "clinic", "patient", "სამედიცინო", "კლინიკ", "პაციენტ", "რეგისტრატორ"]
        elif target_industry == "customer_service" and not direct_signals:
            direct_signals = ["support", "customer", "client", "call center", "helpdesk", "მხარდაჭერ", "ოპერატორ", "ქოლ"]
        for tok in re.split(r"[\s/&|,-]+", primary_role):
            if len(tok) >= 4 and tok not in ("engineer", "specialist", "coordinator", "junior", "associate", "senior") and tok not in direct_signals:
                direct_signals.append(tok)

        adj_signals = [str(s).lower() for s in (search_q.get("adjacent_keywords") or []) if len(str(s)) >= 3]
        c_list = [str(s).lower() for s in (candidate_skills or parsed_skills.get("verified_skills") or parsed_skills.get("all_skills") or [])]
        r_list = [str(s).lower() for s in (required_skills or [])]
        overlap_count = sum(1 for r in r_list if any(r in c or c in r for c in c_list))

        edu_entries = parsed_skills.get("education") or []
        courses_list = [str(c).lower() for c in (parsed_skills.get("courses_and_certifications") or []) if c]
        eligible_internships = bool(parsed_skills.get("eligible_internships") or edu_entries or courses_list or float(parsed_skills.get("years_of_experience") or 1.5) <= 2.5)
        edu_tokens = [
            tok.lower()
            for e in edu_entries
            if isinstance(e, dict)
            for tok in re.split(r"[\s/,&()-]+", f"{e.get('degree', '')} {e.get('field_of_study', '')}")
            if len(tok) >= 4 and tok.lower() not in ("bachelor", "master", "degree", "university", "science", "arts", "present", "student")
        ]
        is_intern_role = any(w in title_lower for w in ("intern", "trainee", "graduate", "apprentice", "სტაჟიორ", "დამწყებ", "სასწავლო"))

        # 1. Public Sector & Internship Portal (hr.gov.ge) — match by domain, tech, or academic/internship track
        if portal == "hr.gov.ge":
            it_gov_signals = ["it", "ინფორმაციულ ტექნოლოგ", "ტექნოლოგ", "პროგრამ", "მონაცემ", "ანალიტ", "სისტემ", "კიბერ", "ქსელ", "ტესტ", "მხარდაჭერ", "sql", "developer"]
            is_tech_cand = target_industry in ("qa_tech", "software_engineering", "data_analytics")
            has_domain_hit = any(sig in combined for sig in (direct_signals + adj_signals + edu_tokens))
            has_tech_hit = is_tech_cand and any(
                (re.search(r"\b" + re.escape(t) + r"\b", combined) if len(t) <= 3 else (t in combined))
                for t in it_gov_signals
            )
            if has_domain_hit or has_tech_hit or overlap_count >= 1 or target_industry == "public_admin_legal" or (eligible_internships and is_intern_role and any(tok in combined for tok in (direct_signals + edu_tokens))):
                return ("PUBLIC_INTERNSHIP", "Public Sector & Graduate Internship (HR.gov.ge)")
            return ("NONE", f"Domain Gate: '{job_title}' on HR.gov.ge does not match candidate's {target_industry} / education profile.")

        # Graduate / Corporate Internship matching via Education + Coursework
        if is_intern_role and eligible_internships and (
            any(sig in combined for sig in (direct_signals + adj_signals + edu_tokens)) or overlap_count >= 1
        ):
            return ("ADJACENT", f"Internship / Graduate Track ({parsed_skills.get('primary_role') or target_industry})")

        if any(sig in title_lower for sig in direct_signals) or (
            target_industry in ("receptionist_hospitality", "healthcare_hospital", "customer_service", "logistics_supply_chain", "finance_accounting")
            and any(sig in combined[:240] for sig in direct_signals)
        ):
            return ("DIRECT", parsed_skills.get("primary_role") or "Direct Role Match")

        # 2. Adjacent Role / Transferable Skill Alignment
        matched_adj_role = adjacent_roles[0] if adjacent_roles else "Transferable Adjacent Role"

        # Match explicit adjacent role titles first
        for adj_r in adjacent_roles:
            role_words = [w.lower() for w in re.split(r"[\s/&(),.-]+", adj_r) if len(w) >= 4 and w.lower() not in ("junior", "associate", "specialist", "engineer", "l2/l3", "l1/l2")]
            if any(w in title_lower for w in role_words):
                return ("ADJACENT", adj_r)

        # Match transferable candidate skills against job requirements (>= 2 core skills or >= 50% overlap)
        has_adj_sig = any(sig in title_lower or sig in combined[:300] for sig in adj_signals)

        # Require either explicit adjacent-role keywords or strong >= 2 transferable skills overlap
        if overlap_count >= 2 or (has_adj_sig and overlap_count >= 1) or (
            has_adj_sig and target_industry in ("logistics_supply_chain", "finance_accounting", "marketing_growth", "sales_bd", "hr_recruiting", "public_admin_legal", "general_professional")
        ):
            return ("ADJACENT", matched_adj_role)

        return ("NONE", f"Domain Gate: '{job_title}' does not align with candidate's primary profile or transferable skills.")

    def evaluate_job_tiered(
        self,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        current_status: str = "DISCOVERED",
        existing_rationale: str = "",
        portal: str = "custom",
    ) -> Dict[str, Any]:
        """
        Universal Multi-Tier Optimal Matching Algorithm:
        - Enforces Strict 2.0-Year Experience Guard.
        - Categorizes matches into Tier 1 DIRECT (>= 80%), Tier 2 ADJACENT (65-79% / transferable skills),
          and Tier 3 PUBLIC_INTERNSHIP (hr.gov.ge).
        """
        if current_status == "FILTERED_OUT":
            return {
                "suitability_score": 0.0,
                "status": "FILTERED_OUT",
                "match_rationale": existing_rationale or "Requires local language",
                "matched_skills": [],
                "missing_skills": [],
                "match_tier": "DIRECT",
                "adjacent_role_tag": None,
                "skill_overlap_pct": None,
            }

        candidate_years = float(parsed_skills.get("years_of_experience") or 1.5)
        max_allowed = parsed_skills.get("max_allowed_years")
        candidate_seniority = str(parsed_skills.get("seniority_level") or "JUNIOR")

        sen_passed, sen_reason = self.validate_seniority_gate(
            candidate_years, candidate_seniority, title, description, max_allowed_years=max_allowed
        )
        if not sen_passed:
            logger.info("[MATCHER REJECT] [%s] '%s' -> %s", portal, title, sen_reason)
            return {
                "suitability_score": 0.0,
                "status": "FILTERED_OUT",
                "match_rationale": sen_reason,
                "matched_skills": [],
                "missing_skills": [],
                "match_tier": "DIRECT",
                "adjacent_role_tag": None,
                "skill_overlap_pct": None,
            }

        # Fail-Safe Foreign Remote Gate: Foreign portal jobs (Djinni, JustJoin, DOU, LinkedIn non-GE)
        # MUST be 100% remote from Georgia — disqualify any hybrid or on-site role.
        if portal in ("djinni.co", "justjoin.it", "dou.ua") or portal.startswith("linkedin"):
            from .scrapers.base_scraper import evaluate_remote_and_language_gate
            cand_langs = parsed_skills.get("spoken_languages") or []
            _, gate_status, gate_reason, _ = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text="Remote" if portal in ("djinni.co", "justjoin.it", "dou.ua") else "International",
                portal=portal,
                candidate_languages=cand_langs,
            )
            if gate_status == "FILTERED_OUT":
                logger.info("[MATCHER REJECT] [%s] '%s' -> %s", portal, title, gate_reason)
                return {
                    "suitability_score": 0.0,
                    "status": "FILTERED_OUT",
                    "match_rationale": gate_reason,
                    "matched_skills": [],
                    "missing_skills": [],
                    "match_tier": "DIRECT",
                    "adjacent_role_tag": None,
                    "skill_overlap_pct": None,
                }

        required_skills = self.extract_job_requirements(title, description)

        # Build candidate skill set dynamically from verified_skills + all taxonomy buckets
        candidate_skills: List[str] = []
        for k in [
            "verified_skills", "all_skills", "qa_automation", "manual_qa",
            "languages", "api_and_performance", "cicd_and_devops", "tools", "frameworks",
        ]:
            vals = parsed_skills.get(k, [])
            if isinstance(vals, list):
                for v in vals:
                    if str(v) and str(v) not in candidate_skills:
                        candidate_skills.append(str(v))

        # Domain / Tier alignment check
        tier_hint, tier_label = self.classify_domain_alignment(
            parsed_skills, title, description, portal=portal,
            candidate_skills=candidate_skills, required_skills=required_skills,
        )
        if tier_hint == "NONE":
            logger.info("[MATCHER REJECT] [%s] '%s' -> %s", portal, title, tier_label)
            return {
                "suitability_score": 0.0,
                "status": "FILTERED_OUT",
                "match_rationale": tier_label,
                "matched_skills": [],
                "missing_skills": [],
                "match_tier": "DIRECT",
                "adjacent_role_tag": None,
                "skill_overlap_pct": None,
            }

        cand_lower = {s.lower() for s in candidate_skills}
        cand_blob = " ".join(candidate_skills).lower()
        has_automation_stack = bool(parsed_skills.get("qa_automation")) or any(
            w in cand_blob for w in ["playwright", "selenium", "cypress", "pytest", "automation"]
        )
        has_manual_stack = bool(parsed_skills.get("manual_qa")) or any(
            w in cand_blob for w in ["manual", "test case", "bug report", "exploratory", "postman", "test design"]
        )

        matched: List[str] = []
        missing: List[str] = []
        missing_specialties: List[str] = []

        for req in required_skills:
            rl = req.lower()
            is_matched = False
            if rl == "qa automation" and has_automation_stack:
                is_matched = True
            elif rl == "manual testing" and has_manual_stack:
                is_matched = True
            elif rl in cand_lower or rl in cand_blob or any(rl in c or c in rl for c in cand_lower):
                is_matched = True

            if is_matched:
                matched.append(req)
            else:
                missing.append(req)
                if req in self.SPECIALIZED_PLATFORMS:
                    missing_specialties.append(req)

        title_lower = (title or "").lower()
        desc_lower = (description or "").lower()

        # Check for unpossessed specialized platforms mentioned prominently in title
        title_specialty_mismatch = any(
            re.search(r"\b" + re.escape(sp.lower()) + r"\b", title_lower) and sp.lower() not in cand_blob
            for sp in self.SPECIALIZED_PLATFORMS
        )
        if title_specialty_mismatch:
            return {
                "suitability_score": 35.0,
                "status": "FILTERED_OUT",
                "match_rationale": f"Suitability Gate: Role requires specialized stack ({', '.join(missing_specialties or ['domain specialty'])}) not present in skills.md.",
                "matched_skills": matched,
                "missing_skills": missing,
                "match_tier": "DIRECT",
                "adjacent_role_tag": None,
                "skill_overlap_pct": None,
            }

        if required_skills:
            raw_ratio = len(matched) / len(required_skills)
            penalty = 20.0 * len(missing_specialties)
            if tier_hint == "ADJACENT":
                score = round(min(84.0, max(65.0, (raw_ratio * 35.0) + 52.0 - penalty)), 1)
            else:
                score = round(min(98.0, max(25.0, (raw_ratio * 78.0) + 22.0 - penalty)), 1)
        else:
            if tier_hint == "PUBLIC_INTERNSHIP":
                is_entry = any(w in title_lower for w in ["სტაჟიორ", "დამწყებ", "ასისტენტ", "intern", "trainee", "junior", "სპეციალისტ"])
                score = 76.0 if is_entry else 64.0
            elif tier_hint == "ADJACENT":
                score = 72.0
            elif any(w in title_lower for w in ["ავტომატიზაცი", "automation", "sdet"]) and has_automation_stack:
                score = 84.0
                matched = ["QA Automation"]
            elif any(w in title_lower for w in ["software qa", "qa engineer", "ტესტერ"]) and "report" not in title_lower and "რეპორტ" not in title_lower:
                score = 68.0 if any(w in desc_lower for w in ["სტაჟირების პროგრამა", "კურსი უკვე გაიარა"]) else 80.0
            else:
                score = 82.0 if tier_hint == "DIRECT" else 55.0

        MIN_SUITABILITY_SCORE = 60.0
        overlap_pct = int(round((len(matched) / len(required_skills)) * 100)) if required_skills else int(round(score))
        overlap_pct = max(65, min(98, overlap_pct)) if tier_hint == "ADJACENT" else overlap_pct

        # Determine final Match Tier cleanly
        if tier_hint == "PUBLIC_INTERNSHIP":
            final_tier = "PUBLIC_INTERNSHIP"
        elif tier_hint == "ADJACENT" or (tier_hint == "DIRECT" and 60.0 <= score < 80.0):
            final_tier = "ADJACENT" if (tier_hint == "ADJACENT" or score < 75.0) else "DIRECT"
        else:
            final_tier = "DIRECT"

        adjacent_tag = f"Adjacent Opportunity: {overlap_pct}% Skill Overlap ({tier_label})" if final_tier == "ADJACENT" else None

        if current_status in ("APPLIED", "REJECTED"):
            new_status = current_status
        elif score < MIN_SUITABILITY_SCORE:
            return {
                "suitability_score": score,
                "status": "FILTERED_OUT",
                "match_rationale": f"Suitability Gate: {score}% match is below {int(MIN_SUITABILITY_SCORE)}% threshold (Missing: {', '.join(missing[:4]) or 'stack alignment'}).",
                "matched_skills": matched,
                "missing_skills": missing,
                "match_tier": final_tier,
                "adjacent_role_tag": None,
                "skill_overlap_pct": None,
            }
        elif score >= 75.0:
            new_status = "STAGED"
        else:
            new_status = "AUDITED"

        matched_str = ", ".join(matched[:6]) if matched else "Transferable competencies"
        missing_str = ", ".join(missing[:4]) if missing else "None (100% core requirement coverage)"
        if final_tier == "ADJACENT":
            rationale = (
                f"Your {matched_str} skills cover {overlap_pct}% of this {tier_label} role. | "
                f"Match: {score}% | Missing: {missing_str}"
            )
        elif final_tier == "PUBLIC_INTERNSHIP":
            rationale = (
                f"Public Sector & Entry/Internship Opportunity ({score}% fit) | "
                f"Matched: {matched_str}"
            )
        else:
            queue_note = "Direct Role Match — auto-promoted to STAGED." if new_status == "STAGED" else "Direct Role Match (60-74%)."
            rationale = (
                f"Suitability {score}% | Matched ({len(matched)}/{len(required_skills)}): {matched_str} | "
                f"Missing: {missing_str}. {queue_note}"
            )

        return {
            "suitability_score": score,
            "status": new_status,
            "match_rationale": rationale,
            "matched_skills": matched,
            "missing_skills": missing,
            "match_tier": final_tier,
            "adjacent_role_tag": adjacent_tag,
            "skill_overlap_pct": overlap_pct if final_tier == "ADJACENT" else None,
        }

    def evaluate_job(
        self,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        current_status: str = "DISCOVERED",
        existing_rationale: str = "",
        portal: str = "custom",
    ) -> Tuple[float, str, str, List[str], List[str]]:
        """Backwards-compatible 5-tuple wrapper over evaluate_job_tiered."""
        res = self.evaluate_job_tiered(
            title=title,
            description=description,
            parsed_skills=parsed_skills,
            current_status=current_status,
            existing_rationale=existing_rationale,
            portal=portal,
        )
        return (
            res["suitability_score"],
            res["status"],
            res["match_rationale"],
            res["matched_skills"],
            res["missing_skills"],
        )


matcher_service = MatcherService()
