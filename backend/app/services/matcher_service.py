import logging
import re
from datetime import datetime
from typing import Dict, Any, Iterable, List, Optional, Tuple
from .gemini_service import MULTI_INDUSTRY_SKILLS, gemini_service

logger = logging.getLogger(__name__)

_PUBLIC_SECTOR_ORG_PATTERNS = (
    "სსიპ",
    "ა(ა)იპ",
    "სამინისტრო",
    "მერია",
    "საკრებულო",
    "პარლამენტ",
    "სასამართლო",
    "პროკურატურ",
    "ეროვნული ბანკ",
    "სახელმწიფო",
    "საჯარო რეესტრ",
    "შემოსავლების სამსახურ",
    "საქსტატ",
    "მუნიციპალიტეტ",
    "საელჩო",
    "გუბერნატორ",
    "ministry of",
    "municipality of",
    "parliament of",
    "national bank of georgia",
    "public service hall",
    "state agency",
    "lepl ",
    "embassy of",
)


def is_public_sector_vacancy(portal: str, company: str = "", title: str = "", description: str = "") -> bool:
    """
    Returns True ONLY for genuine state/government public-sector roles:
    - All listings on vacancy.hr.gov.ge
    - Verified state ministries, LEPLs (სსიპ / ა(ა)იპ), municipalities, or public agencies on jobs.ge / hr.ge.
    Private companies (e.g. Andersen, Itransition, ProCredit, TBC) NEVER return True.
    """
    p_low = (portal or "").strip().lower()
    if p_low == "hr.gov.ge":
        return True
    if p_low not in ("jobs.ge", "hr.ge"):
        return False
    comp_low = f"{company} {title}".lower()
    header_slice = (description or "")[:220].lower()
    if any(tok in comp_low for tok in _PUBLIC_SECTOR_ORG_PATTERNS):
        return True
    if any(tok in header_slice for tok in ("სსიპ ", "ა(ა)იპ ", "საქართველოს სამინისტრო", "მუნიციპალიტეტის მერია")):
        return True
    return False

SKILL_MATCH_ALIASES: Dict[str, set[str]] = {
    "js": {"javascript", "js"},
    "javascript": {"javascript", "js"},
    "ts": {"typescript", "ts"},
    "typescript": {"typescript", "ts"},
    "k8s": {"kubernetes", "k8s"},
    "kubernetes": {"kubernetes", "k8s"},
    "postgres": {"postgresql", "postgres"},
    "postgresql": {"postgresql", "postgres"},
    "rest api": {"rest api", "restful api", "restful apis", "rest apis"},
    "restful api": {"rest api", "restful api", "restful apis", "rest apis"},
    "ci/cd": {"ci/cd", "cicd", "continuous integration"},
    "gitlab ci": {"gitlab ci", "gitlab"},
    "github actions": {"github actions"},
    "selenium webdriver": {"selenium webdriver", "selenium"},
    "selenium": {"selenium", "selenium webdriver"},
    "py": {"python", "py"},
    "python": {"python", "py"},
    "golang": {"go", "golang"},
    "go": {"go", "golang"},
    "csharp": {"c#", "csharp"},
    "c#": {"c#", "csharp"},
}


def _contains_skill_token(haystack: str, term: str) -> bool:
    if not haystack or not term:
        return False
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])"
    return bool(re.search(pattern, haystack, re.IGNORECASE))


def skills_match_token(
    req_skill: str,
    candidate_skills: Iterable[str],
    cand_blob: str = "",
) -> bool:
    """Word/token-boundary and alias-aware skill matcher preventing accidental substring hits."""
    req_clean = (req_skill or "").strip().lower()
    if not req_clean:
        return False
    req_variants = SKILL_MATCH_ALIASES.get(req_clean, {req_clean})
    cand_norm: set[str] = set()
    for raw_c in (candidate_skills or []):
        cl = str(raw_c or "").strip().lower()
        if not cl:
            continue
        cand_norm.add(cl)
        cand_norm.update(SKILL_MATCH_ALIASES.get(cl, ()))
    if any(rv in cand_norm for rv in req_variants):
        return True
    for cl in cand_norm:
        if any(_contains_skill_token(cl, rv) for rv in req_variants if len(rv) >= 2):
            return True
    if cand_blob:
        blob_low = cand_blob.lower()
        for rv in req_variants:
            if len(rv) == 1 and rv not in ("r", "c"):
                continue
            if _contains_skill_token(blob_low, rv):
                return True
    return False

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
    "fastapi": "FastAPI",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "vividus": "VIVIDUS",
    "allure": "Allure",
    "agile": "Agile",
    "scrum": "Scrum",
    "sdlc": "SDLC",
    "stlc": "STLC",
    "pom": "POM",
    "bva": "Boundary Value Analysis",
    "ep": "Equivalence Partitioning",
}

_AI_PERSONA_OR_META_SKILL_RE = re.compile(
    r"\b(?:hiring\s+manager|technical\s+recruiter|career\s+strategist|interview\s+coach|"
    r"interviewer|automation\s+mentor|career\s+coach|ai\s+assistant|senior\s+qa\s+automation\s+engineer|"
    r"do\s+not\s+claim|treat\s+the|potential\s+transferable|verified\s+work\s+experience)\b",
    re.I,
)

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
    s = s.strip("•·–—-.,:;()[]{}\uf0b7").strip()
    if not s or len(s) < 2 or len(s) > 36:
        return ""
    if "@" in s or "http" in s.lower() or "://" in s or "•" in raw:
        return ""
    if ("(" in s) != (")" in s):
        return ""
    if s.lower() in {
        "test", "functional", "regression", "console", "severity", "priority",
        "technical tools", "headers", "payload analysis", "reproduction steps",
        "defect reporting", "auth tokens", "network",
    }:
        return ""
    if _DATE_OR_PROSE_RE.search(s) or _PROSE_START_RE.search(s) or _AI_PERSONA_OR_META_SKILL_RE.search(s):
        return ""
    # Reject hyphenated slug identifiers (e.g. giorgi-career-intelligence-interview-coach)
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", s):
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


_WORK_SECTION_RE = re.compile(
    r"^##+\s*(?:work\s+experience|professional\s+experience|employment(?:\s+history)?|experience|career\s+history|სამუშაო\s+გამოცდილება|გამოცდილება)\b",
    re.I,
)
_NON_WORK_SECTION_RE = re.compile(
    r"^##+\s*(?:education|academic|skills|certifications|projects|languages|courses|references|განათლება|უნარები|პროექტები)\b",
    re.I,
)
_DATE_RANGE_RE = re.compile(
    r"(?:(?:0?[1-9]|1[0-2])\s*/\s*)?(20\d{2}|19[89]\d)\s*[–—\-]\s*(?:(?:0?[1-9]|1[0-2])\s*/\s*)?(20\d{2}|present|current|now|დღემდე)",
    re.I,
)


def _infer_experience_years_from_dates(text: str) -> Optional[float]:
    """Infers cumulative non-overlapping years from explicit Work Experience date ranges (excluding internships/education)."""
    in_work = False
    intervals: List[Tuple[int, int]] = []
    curr_year = datetime.now().year
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("##"):
            if _WORK_SECTION_RE.match(line):
                in_work = True
                continue
            if _NON_WORK_SECTION_RE.match(line):
                in_work = False
                continue
        if not in_work:
            continue
        low = line.lower()
        if any(w in low for w in ("intern", "internship", "trainee", "student", "bootcamp", "სტაჟიორ", "სასწავლო")):
            continue
        for m in _DATE_RANGE_RE.finditer(line):
            start_y = int(m.group(1))
            end_raw = m.group(2).lower()
            end_y = curr_year if end_raw in ("present", "current", "now", "დღემდე") else int(end_raw)
            if 1990 <= start_y <= curr_year and start_y <= end_y <= curr_year + 1:
                intervals.append((start_y, max(start_y, end_y)))
    if not intervals:
        return None
    intervals.sort()
    merged: List[Tuple[int, int]] = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    total = sum(max(1, e - s) if e > s else 0.5 for s, e in merged)
    return round(min(30.0, float(total)), 1) if total > 0 else None


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
        pass

    @property
    def client(self):
        return gemini_service.client

    def parse_skills_markdown(self, raw_markdown: str, enrich_with_ai: bool = False) -> Dict[str, Any]:
        """
        Parses raw_markdown (from skills.md) into structured taxonomy for CandidateProfile.parsed_skills.
        Uses Gemini 2.5 Flash if available, enriched with deterministic taxonomy matching.
        """
        text = re.sub(r"\A---\s*\n[\s\S]*?\n---\s*\n", "", raw_markdown or "")
        text = text.replace("\uf0b7", "- ").replace("", "- ")
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
            "years_of_experience": None,
            "experience_status": "unknown",
            "seniority_level": "JUNIOR",
            "all_skills": [],
        }

        # Extract years of experience from explicit statement or verified Work Experience date ranges
        yr_match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წელი|წლიანი)", lower_text)
        if yr_match:
            taxonomy["years_of_experience"] = float(yr_match.group(1))
            taxonomy["experience_status"] = "confirmed"
        else:
            inferred_years = _infer_experience_years_from_dates(text)
            if inferred_years is not None and inferred_years >= 1.0:
                taxonomy["years_of_experience"] = inferred_years
                taxonomy["experience_status"] = "confirmed"
            elif any(w in lower_text for w in ["portfolio project", "entry-level", "junior", "intern", "trainee", "დამწყები", "სტაჟირება"]):
                taxonomy["years_of_experience"] = None
                taxonomy["experience_status"] = "internship_or_project"

        # Infer seniority level transparently (treat unknown/entry as JUNIOR ceiling)
        exp = float(taxonomy["years_of_experience"]) if taxonomy["years_of_experience"] is not None else 0.0
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

        # Extract bullet items strictly under dedicated Skills headings (including plain-text PDF/DOCX headings)
        in_skills = False
        _plain_sec_re = re.compile(
            r"^(?:##+\s*|#\s*)?(?:core\s+competencies(?:\s*&\s*technical\s+skills)?|technical\s+skills(?:\s*&\s*stack)?|"
            r"core\s+skills|skills|summary|professional\s+summary|work\s+experience|professional\s+experience|"
            r"experience|education(?:\s*&\s*(?:technical\s+training|specialized\s+training|certifications))?|"
            r"projects|relevant\s+projects|languages|spoken\s+languages)\s*:?$",
            re.I,
        )
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("## ") or _plain_sec_re.match(s):
                header_l = s.lower()
                is_exp_header = any(w in header_l for w in ["experience", "history", "work", "project", "education", "summary", "language", "გამოცდილება"])
                in_skills = (not is_exp_header) and any(
                    w in header_l for w in ["skill", "stack", "tech", "competenc", "უნარ", "კომპეტენც"]
                )
                continue
            if s.startswith("### ") or (s.startswith("# ") and not s.startswith("## ")):
                in_skills = False
                continue
            if in_skills and s.startswith(("-", "*", "•")):
                # Stop collecting as skills if bullet looks like a company/date sub-header
                if _DATE_OR_PROSE_RE.search(s):
                    continue
                cleaned = re.sub(r"^[-*•]\s*(?:\*\*[^*]+?\*\*:?|[A-Za-z &/]{2,36}:)\s*", "", s)
                for part in re.split(r"[,;/|]", cleaned):
                    token = _clean_skill_token(part)
                    if token and all(existing.lower() != token.lower() for existing in all_skills):
                        all_skills.append(token)

        all_skills = dedupe_skills_case_insensitive(all_skills)
        taxonomy["frameworks"] = dedupe_skills_case_insensitive(list(taxonomy["qa_automation"]))
        taxonomy["tools"] = dedupe_skills_case_insensitive(list(taxonomy["api_and_performance"]) + list(taxonomy["cicd_and_devops"]))
        taxonomy["all_skills"] = all_skills

        # Optional AI enrichment only when explicitly requested (avoids double Gemini calls on upload)
        if enrich_with_ai and gemini_service.is_available:
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
            gem_data = gemini_service.generate_json(
                prompt,
                task_type="skills_taxonomy",
                model_tier="fast",
                temperature=0.1,
                ttl_seconds=3600,
            )
            if isinstance(gem_data, dict):
                for k in ["qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops"]:
                    if isinstance(gem_data.get(k), list):
                        merged = list(dict.fromkeys(taxonomy[k] + [str(x) for x in gem_data[k]]))
                        taxonomy[k] = merged

        return taxonomy

    SPECIALIZED_PLATFORMS = [
        "Game Testing", "Gamedev", "Unity", "iGaming", "Swift", "Kotlin", "Ruby", "PHP",
    ]
    TECH_ONLY_SPECIALTIES = ["Salesforce", "WordPress", "Shopify", "SAP"]

    def extract_job_requirements(self, title: str, description: str) -> List[str]:
        """Extracts actual required technical and domain skills from job title + description without fabrication."""
        cleaned_desc = re.sub(r"(?:https?://\S+|www\.\S+|\S+@\S+)", " ", description or "")
        combined = f"{title}\n{cleaned_desc}".lower()
        required: List[str] = []

        for _category, items in QA_TAXONOMY_CATALOG.items():
            for skill in items:
                pattern = r"(?<![A-Za-z0-9_])" + re.escape(skill.lower()) + r"(?![A-Za-z0-9_])"
                if re.search(pattern, combined) and skill not in required:
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
        # Capture opening role announcement sentence (e.g. ProCredit "აცხადებს ვაკანსიას ... (Middle / Senior QA) პოზიციაზე")
        opening_m = re.search(
            r"(?:აცხადებს\s+ვაკანსიას[^\n.]{0,160}|opening\s+for\s+the\s+position\s+of[^\n.]{0,120}|ad\s+title:\s*[^\n|]{0,100})",
            (job_description or "")[:650],
            re.IGNORECASE,
        )
        opening_scope = f"{title_lower} {opening_m.group(0).lower() if opening_m else ''}"

        exec_titles = [
            "lead", "principal", "head of", "staff", "director", "architect", "chief", "vp",
            "middle+", "mid+", "mid/senior", "middle/senior", "middle / senior", "mid / senior", "mid-senior",
            "ლიდი", "ხელმძღვანელი", "დირექტორი", "მთავარი", "წამყვანი",
        ]
        senior_titles = ["senior", "sr.", "sr ", "უფროსი", "სინიორ"]
        tech_manager_titles = ["qa manager", "engineering manager", "test manager", "it manager"]

        # Extract all experience requirement signals (ranges e.g. "2-3 years", "3-5 years", "2+ years", "მინიმუმ 2 წელი", "ორწლიანი")
        found_years: List[float] = []
        for ka_word, yrs_val in (("ორწლიან", 2.0), ("სამწლიან", 3.0), ("ოთხწლიან", 4.0), ("ხუთწლიან", 5.0)):
            if ka_word in combined:
                found_years.append(yrs_val)

        # 1. Range format (e.g. "1-2 years", "2-3 years", "3-5 წელი", "2–4 роки")
        # Use lower bound for entry ranges ("1-2 years" requires >=1 yr), upper bound for >=2 yr ranges ("2-3 years")
        for rm in re.finditer(r"(\d+(?:\.\d+)?)\s*[–\-]\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|років|лет)", combined):
            try:
                low_v, high_v = float(rm.group(1)), float(rm.group(2))
                found_years.append(high_v if low_v >= 2.0 else low_v)
            except ValueError as err:
                logger.debug("Skipping malformed experience range '%s': %s", rm.group(0), err)

        # 2. Minimum / at least format (e.g. "მინიმუმ 3 წელი", "at least 3 years", "სულ მცირე 3 წელი", "досвід від 3 років")
        for mm in re.finditer(r"(?:მინიმუმ|სულ\s+მცირე|არანაკლებ|at least|minimum of|minimum|min\.?|від|от)\s*[:\-–]?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|рок(?:ів)?|лет|года)?", combined):
            try:
                found_years.append(float(mm.group(1)))
            except ValueError as err:
                logger.debug("Skipping malformed minimum experience '%s': %s", mm.group(0), err)

        # 3. Direct years of experience (e.g. "3+ years of experience", "2+ years", "3 წლიანი გამოცდილება")
        for ym in re.finditer(r"(\d+(?:\.\d+)?)\s*(\+)?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|рок(?:ів)?|лет|года)(?:\s+of)?\s*(?:experience|გამოცდილება|досвід|опыт)?", combined):
            try:
                val = float(ym.group(1))
                # Explicit "2+ years" means AT LEAST 2 years (exceeds entry/junior <=2.0 cap)
                if ym.group(2) == "+" and val >= 2.0:
                    val = round(val + 0.1, 1)
                found_years.append(val)
            except ValueError as err:
                logger.debug("Skipping malformed direct experience '%s': %s", ym.group(0), err)

        # 4. Keyed requirements (e.g. "Experience: 3 years", "გამოცდილება: 3 წელი")
        for em in re.finditer(r"(?:experience|გამოცდილება|досвід|опыт)\s*[:\-–]\s*(\d+(?:\.\d+)?)", combined):
            try:
                found_years.append(float(em.group(1)))
            except ValueError as err:
                logger.debug("Skipping malformed keyed experience '%s': %s", em.group(0), err)

        # Filter out calendar years (2020+) and extreme values, keeping legitimate professional experience requirements
        valid_exp = [y for y in found_years if 0.5 <= y <= 15.0]
        job_req_years = max(valid_exp) if valid_exp else None

        # Direct regex guard for 3+ years (and 2+ years for entry-level candidates)
        has_3_plus_guard = bool(
            re.search(r"(?<![\d.])(?:[3-9]|\d{2,})(?:\.\d+)?\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|років|лет)\b", combined)
            or re.search(r"(?:მინიმუმ|სულ\s+მცირე|არანაკლებ|at least|minimum of|від|от)\s*[:\-–]?\s*(?<![\d.])(?:[3-9]|\d{2,})(?:\.\d+)?", combined)
        )
        has_2_plus_guard = bool(
            re.search(r"(?<![\d.])2\+\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|років|лет)\b", combined)
            or re.search(r"(?:მინიმუმ|სულ\s+მცირე|არანაკლებ|at least|minimum of|minimum|від|от)\s*[:\-–]?\s*2(?:\.0)?\+?\s*(?:years?|yrs?|წ(?:ელი|ლიანი)?|рок(?:ів)?|лет)", combined)
        )

        if max_allowed_years is not None:
            cap = float(max_allowed_years)
        elif candidate_years <= 0.5:
            cap = 1.0
        elif candidate_years <= 2.0:
            cap = min(round(candidate_years + 0.5, 1), 2.0)
        elif candidate_years <= 2.5:
            cap = round(candidate_years + 0.5, 1)
        elif candidate_years <= 5.0:
            cap = round(candidate_years + 1.5, 1)
        else:
            cap = round(candidate_years + 2.5, 1)

        # Gate 1: Entry / Junior Experience Guard (adapts dynamically to 1.0 yr entry vs 1.5 yr junior vs 2.0-2.5 yr junior-mid)
        if candidate_years <= 2.5:
            for s in exec_titles + senior_titles + tech_manager_titles:
                if any(ch in s for ch in ("+", "/", ".")):
                    matched_s = s in opening_scope
                else:
                    matched_s = bool(re.search(r"\b" + re.escape(s) + r"\b", opening_scope))
                if matched_s:
                    return (
                        False,
                        f"Disqualified by Seniority Gate: Role requires {s.title()}, exceeding candidate experience ({cap:.1f} yrs max).",
                    )
            # Entry-level (<1.5 yrs, cap <=1.5) candidates also reject standalone Middle / Mid-Level titles (unless Junior/Middle)
            if cap <= 1.5 and not any(j in opening_scope for j in ("junior", "intern", "trainee", "უმცროს", "სტაჟიორ", "დამწყებ")):
                if re.search(r"\b(?:middle|mid-level|mid\s+level)\b", opening_scope):
                    return (
                        False,
                        f"Disqualified by Seniority Gate: Role targets Mid-Level experience, exceeding entry/junior ceiling ({cap:.1f} yrs).",
                    )
            if cap <= 2.0 and has_3_plus_guard:
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires 3+ years experience (strictly capped at {cap:.1f} yrs).",
                )
            if (candidate_years < 1.5 or cap < 2.0) and has_2_plus_guard:
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires 2+ years experience, exceeding entry/junior cap ({cap:.1f} yrs max).",
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

    def classify_domain_alignment(
        self,
        parsed_skills: Dict[str, Any],
        job_title: str,
        job_description: str,
        portal: str = "custom",
        candidate_skills: Optional[List[str]] = None,
        required_skills: Optional[List[str]] = None,
        company: str = "",
    ) -> Tuple[str, str]:
        """
        Universal Domain-Agnostic Alignment Classifier:
        Returns (tier_hint, aligned_role_or_reason) where tier_hint is:
        - "DIRECT" -> directly matches candidate's primary role/industry
        - "ADJACENT" -> transferable skills overlap with an optimal adjacent role
        - "PUBLIC_INTERNSHIP" -> vacancy.hr.gov.ge public administration / entry internship
        - "NONE" -> off-domain mismatch
        """
        title_lower = (job_title or "").lower()
        combined = f"{job_title}\n{job_description}".lower()
        target_industry = str(parsed_skills.get("target_industry") or "general_professional").lower()
        search_q = parsed_skills.get("search_queries") or {}
        primary_role = str(parsed_skills.get("primary_role") or parsed_skills.get("headline") or "").lower()
        adjacent_roles = [str(r) for r in (parsed_skills.get("adjacent_roles") or []) if r]

        # Foreign-language-gated title check (e.g. "იტალიურენოვანი მომხმარებელთა მრჩეველი" / "German-speaking")
        cand_spoken = " ".join(str(x).lower() for x in (parsed_skills.get("spoken_languages") or []))
        foreign_title_langs = [
            ("italian", ("italian-speaking", "italian speaking", "იტალიურენოვანი", "იტალიური ენ")),
            ("german", ("german-speaking", "german speaking", "გერმანულენოვანი")),
            ("french", ("french-speaking", "french speaking", "ფრანგულენოვანი")),
            ("spanish", ("spanish-speaking", "spanish speaking", "ესპანურენოვანი")),
            ("turkish", ("turkish-speaking", "turkish speaking", "თურქულენოვანი")),
            ("arabic", ("arabic-speaking", "arabic speaking", "არაბულენოვანი")),
            ("polish", ("polish-speaking", "polish speaking", "პოლონურენოვანი")),
        ]
        for lang_key, markers in foreign_title_langs:
            if any(m in title_lower for m in markers) and lang_key not in cand_spoken:
                return ("NONE", f"Language Gate: '{job_title}' requires {lang_key.title()}, which is not in candidate's CV.")

        # Multi-Industry Recruiter Off-Domain Exclusion Matrix:
        # Prevents clearly unrelated specialist roles (e.g. Call Center for QA/Finance, Nurse for Marketing,
        # Software Engineer for Logistics, Accountant for HR) from leaking into any profession's feed.
        _conflict_groups = (
            (
                "manual_retail",
                ("cashier", "waiter", "bartender", "housekeeper", "driver", "courier", "cleaner", "security guard", "მოლარე", "მიმტანი", "მძღოლი", "კურიერი", "დამლაგებელ", "დაცვის თანამშრომელ"),
                {"receptionist_hospitality", "logistics_supply_chain", "general_professional"},
            ),
            (
                "customer_reception",
                ("customer service", "customer advisor", "customer care", "call center", "call-center", "sales consultant", "sales representative", "receptionist", "front desk", "მომხმარებელთა მრჩეველი", "მომხმარებელთა მომსახურებ", "ქოლ-ცენტრ", "ქოლ ცენტრ", "გაყიდვების კონსულტანტ", "კონსულტანტი", "მიმღები", "რეცეფციონისტ"),
                {"customer_service", "receptionist_hospitality", "sales_bd", "healthcare_hospital", "general_professional"},
            ),
            (
                "clinical_medical",
                ("nurse", "doctor", "physician", "dentist", "pharmacist", "ექთანი", "ექიმი", "ფარმაცევტ"),
                {"healthcare_hospital", "general_professional"},
            ),
            (
                "software_qa_engineering",
                ("software engineer", "backend developer", "frontend developer", "full stack developer", "devops engineer", "qa automation", "sdet", "qa engineer", "პროგრამისტი", "დეველოპერი", "ტესტერი"),
                {"qa_tech", "software_engineering", "data_analytics", "general_professional"},
            ),
            (
                "accounting_audit",
                ("chief accountant", "accountant", "bookkeeper", "tax auditor", "ბუღალტერი", "ბუღალტერ", "აუდიტორი"),
                {"finance_accounting", "public_admin_legal", "general_professional"},
            ),
            (
                "legal_practice",
                ("lawyer", "attorney", "legal counsel", "იურისტი", "ადვოკატი"),
                {"public_admin_legal", "finance_accounting", "general_professional"},
            ),
        )
        default_domain_signals = {
            "qa_tech": ["qa", "quality assurance", "quality engineer", "test engineer", "software test", "manual test", "tester", "sdet", "qa automation", "test automation", "ტესტერ", "ტესტირებ", "ხარისხის უზრუნველყოფ"],
            "software_engineering": ["developer", "software engineer", "backend", "frontend", "full stack", "python engineer", "devops", "პროგრამისტი", "დეველოპერი"],
            "data_analytics": ["data analyst", "business intelligence", "bi analyst", "analytics", "power bi", "tableau", "ანალიტიკოს"],
            "finance_accounting": ["accountant", "accounting", "finance", "financial", "audit", "tax", "payroll", "ifrs", "treasury", "controller", "ბუღალტ", "ფინანს", "აუდიტ"],
            "hr_recruiting": ["hr", "human resources", "recruiter", "talent acquisition", "people operations", "onboarding", "hrbp", "ადამიანური რესურს", "რეკრუტ"],
            "marketing_growth": ["marketing", "seo", "smm", "content", "brand", "growth", "performance marketing", "copywriter", "მარკეტინგ"],
            "sales_bd": ["sales", "account executive", "account manager", "business development", "b2b", "გაყიდვ"],
            "logistics_supply_chain": ["logistics", "supply chain", "procurement", "warehouse", "freight", "dispatch", "inventory", "ლოჯისტიკ", "შესყიდვ", "მომარაგებ"],
            "public_admin_legal": ["legal", "lawyer", "counsel", "compliance", "public policy", "procurement", "იურისტ", "საჯარო"],
            "receptionist_hospitality": ["reception", "front desk", "hospitality", "concierge", "hotel", "guest", "მიმღებ", "რეცეფც", "სასტუმრ", "ადმინისტრატორ"],
            "healthcare_hospital": ["medical", "hospital", "clinic", "patient", "nurse", "pharmacy", "სამედიცინო", "კლინიკ", "პაციენტ", "ექთანი", "რეგისტრატორ"],
            "customer_service": ["support", "customer", "client", "call center", "helpdesk", "მხარდაჭერ", "ოპერატორ", "ქოლ"],
        }
        # QA-specific off-discipline guard: prevent pure Software/Cloud/Security/BizDev/PM titles from leaking via Python/Git overlap
        if target_industry == "qa_tech":
            qa_title_keep = ("qa", "quality", "test automation", "software test", "manual test", "sdet", "support", "data quality", "ტესტ", "ხარისხ", "მხარდაჭერ")
            qa_off_titles = (
                "cloud platform", "backend engineer", "backend developer", "frontend engineer", "frontend developer",
                "full stack", "fullstack", "software engineer", "python engineer", "devops engineer", "site reliability",
                "sre ", "penetration tester", "security engineer", "offensive security", "alliances field",
                "sales engineer", "solutions architect", "analyst relations", "business development",
                "account executive", "product manager", "project manager",
            )
            if any(off in title_lower for off in qa_off_titles) and not any(kp in title_lower for kp in qa_title_keep):
                return ("NONE", f"Domain Gate: '{job_title}' is a non-QA specialist role outside QA & Software Testing.")

        own_override_signals = default_domain_signals.get(target_industry, [])
        for grp_name, grp_signals, allowed_inds in _conflict_groups:
            if target_industry in allowed_inds:
                continue
            if any(sig in title_lower for sig in grp_signals) and not any(
                ov in combined for ov in own_override_signals
            ):
                return (
                    "NONE",
                    f"Domain Gate: '{job_title}' belongs to {grp_name.replace('_', ' ')} outside {target_industry}.",
                )

        # Always merge canonical domain signals with search_queries so localized titles (e.g. "ხარისხის უზრუნველყოფის სპეციალისტი") always match DIRECT
        direct_signals = list(dict.fromkeys(
            list(default_domain_signals.get(target_industry, []))
            + [str(s).lower() for s in (search_q.get("domain_keywords") or []) if len(str(s)) >= 2 and str(s).lower() not in ("python", "sql", "test")]
        ))
        for tok in re.split(r"[\s/&|,-]+", primary_role):
            if len(tok) >= 4 and tok not in ("engineer", "specialist", "coordinator", "junior", "associate", "senior", "manager") and tok not in direct_signals:
                direct_signals.append(tok)

        adj_signals = [str(s).lower() for s in (search_q.get("adjacent_keywords") or []) if len(str(s)) >= 3]
        c_list = [str(s) for s in (candidate_skills or parsed_skills.get("verified_skills") or parsed_skills.get("all_skills") or [])]
        c_blob = " ".join(c_list).lower()
        r_list = [str(s) for s in (required_skills or [])]
        overlap_count = sum(1 for r in r_list if skills_match_token(r, c_list, c_blob))

        edu_entries = parsed_skills.get("education") or []
        courses_list = [str(c).lower() for c in (parsed_skills.get("courses_and_certifications") or []) if c]
        raw_exp_val = parsed_skills.get("years_of_experience")
        eligible_internships = bool(
            parsed_skills.get("eligible_internships")
            or edu_entries
            or courses_list
            or raw_exp_val is None
            or float(raw_exp_val) <= 2.5
        )
        edu_tokens: List[str] = []
        _edu_bilingual_map = {
            "computer": ["it", "software", "ინფორმაციულ", "კომპიუტერულ", "ტექნოლოგ", "პროგრამ"],
            "informatics": ["it", "software", "ინფორმაციულ", "ტექნოლოგ", "მონაცემ"],
            "information": ["it", "ინფორმაციულ", "სისტემ", "ტექნოლოგ"],
            "software": ["developer", "qa", "ტესტ", "პროგრამ", "დეველოპერ"],
            "engineering": ["engineer", "technical", "ტექნიკურ", "ინჟინერ"],
            "business": ["business", "analyst", "operations", "ბიზნეს", "ანალიტ", "ოპერაცი"],
            "economics": ["economic", "finance", "analyst", "ეკონომიკ", "ფინანს", "ანალიტ"],
            "finance": ["finance", "accounting", "audit", "ფინანს", "ბუღალტ", "აუდიტ"],
            "accounting": ["accounting", "finance", "audit", "ბუღალტ", "ფინანს", "აუდიტ"],
            "management": ["project", "coordinator", "operations", "მენეჯმენტ", "პროექტ"],
            "marketing": ["marketing", "brand", "digital", "content", "მარკეტინგ", "კონტენტ"],
            "communications": ["communications", "pr", "marketing", "კომუნიკაცი", "მარკეტინგ"],
            "journalism": ["content", "copywriter", "pr", "media", "კონტენტ", "მედია"],
            "psychology": ["hr", "recruiter", "talent", "people", "ადამიანური რესურს", "რეკრუტ"],
            "logistics": ["logistics", "supply", "procurement", "ლოჯისტიკ", "შესყიდვ"],
            "transport": ["logistics", "freight", "dispatch", "ლოჯისტიკ", "ტრანსპორტ"],
            "tourism": ["hospitality", "hotel", "guest", "ტურიზმ", "სასტუმრ"],
            "hospitality": ["hospitality", "hotel", "front desk", "სასტუმრ", "მიმღებ"],
            "medicine": ["medical", "clinical", "healthcare", "სამედიცინო", "კლინიკ"],
            "pharmacy": ["pharmacy", "clinical", "medical", "ფარმაც", "სამედიცინო"],
            "law": ["legal", "compliance", "იურისტ", "სამართალ"],
            "public": ["public", "policy", "administration", "საჯარო", "ადმინისტრ"],
            "international": ["international", "relations", "policy", "საერთაშორისო", "პოლიტიკ"],
            "mathematics": ["data", "analyst", "analytics", "მონაცემ", "ანალიტ"],
            "statistics": ["data", "analyst", "analytics", "სტატისტიკ", "ანალიტ"],
        }
        for e in edu_entries:
            if not isinstance(e, dict):
                continue
            edu_blob = " ".join(
                [
                    str(e.get("degree") or ""),
                    str(e.get("field_of_study") or ""),
                    str(e.get("focus") or ""),
                    " ".join(str(m) for m in (e.get("modules") or [])[:8]),
                ]
            ).lower()
            for tok in re.split(r"[\s/,&()-]+", edu_blob):
                if len(tok) >= 4 and tok not in ("bachelor", "master", "degree", "university", "science", "arts", "present", "student"):
                    if tok not in edu_tokens:
                        edu_tokens.append(tok)
                    for mapped in _edu_bilingual_map.get(tok, []):
                        if mapped not in edu_tokens:
                            edu_tokens.append(mapped)

        is_intern_role = any(w in title_lower for w in ("intern", "trainee", "graduate", "apprentice", "სტაჟიორ", "სტაჟირებ", "დამწყებ", "სასწავლო"))
        is_pub_sector = is_public_sector_vacancy(portal, company=company, title=job_title, description=job_description)

        # 1. Genuine Public Sector Vacancy (hr.gov.ge or verified state ministries/LEPLs on jobs.ge/hr.ge)
        if is_pub_sector:
            it_gov_signals = ["it", "ინფორმაციულ ტექნოლოგ", "ტექნოლოგ", "პროგრამ", "მონაცემ", "ანალიტ", "სისტემ", "კიბერ", "ქსელ", "ტესტ", "sql", "developer"]
            is_tech_cand = target_industry in ("qa_tech", "software_engineering", "data_analytics")
            has_domain_hit = any(sig in combined for sig in (direct_signals + adj_signals + edu_tokens))
            has_tech_hit = is_tech_cand and any(
                (re.search(r"\b" + re.escape(t) + r"\b", combined) if len(t) <= 3 else (t in combined))
                for t in it_gov_signals
            )
            if has_domain_hit or has_tech_hit or overlap_count >= 1 or target_industry == "public_admin_legal" or (eligible_internships and is_intern_role and any(tok in combined for tok in (direct_signals + edu_tokens))):
                return ("PUBLIC_INTERNSHIP", "Public Sector Vacancy")
            return ("NONE", f"Domain Gate: '{job_title}' does not match candidate's {target_industry} / education profile.")

        # 2. Private-Sector Direct Role Match (including direct-domain Traineeships/Internships like 'QA Manual Trainee' at Andersen!)
        if any(
            (re.search(r"\b" + re.escape(sig) + r"\b", title_lower) if len(sig) <= 3 and sig.isascii() else (sig in title_lower))
            for sig in direct_signals
        ) or (
            target_industry in ("receptionist_hospitality", "healthcare_hospital", "customer_service", "logistics_supply_chain", "finance_accounting")
            and any(sig in combined[:240] for sig in direct_signals)
        ):
            role_lbl = "Entry-Level / Internship" if is_intern_role else (parsed_skills.get("primary_role") or "Direct Role Match")
            return ("DIRECT", role_lbl)

        # 3. Private-Sector Graduate / Entry-Level Internship matching compiled from Education + CV skills (NEVER labeled Public Sector!)
        if is_intern_role and eligible_internships and (
            any(sig in combined for sig in (adj_signals + edu_tokens)) or overlap_count >= 1
        ):
            edu_hit = any(tok in combined for tok in edu_tokens)
            label = "Entry-Level / Graduate Internship" if edu_hit else "Entry-Level / Internship"
            return ("ADJACENT", label)

        # 2. Adjacent Role / Transferable Skill Alignment (require real technical alignment for tech profiles)
        matched_adj_role = adjacent_roles[0] if adjacent_roles else "Transferable Adjacent Role"

        # Match explicit adjacent role titles only when not a generic non-technical support word
        generic_noise_words = {"junior", "associate", "specialist", "engineer", "l2/l3", "l1/l2", "support", "assistant", "manager", "operations"}
        for adj_r in adjacent_roles:
            role_words = [w.lower() for w in re.split(r"[\s/&(),.-]+", adj_r) if len(w) >= 4 and w.lower() not in generic_noise_words]
            if role_words and any(w in title_lower for w in role_words):
                return ("ADJACENT", adj_r)
            if "technical support" in title_lower or "application support" in title_lower or "ტექნიკური მხარდაჭერ" in title_lower:
                if overlap_count >= 1 or any(t in combined for t in ("sql", "api", "linux", "jira", "postman", "ლოგ", "მონიტორინგ")):
                    return ("ADJACENT", "Technical Support Engineer L2/L3")

        # Match transferable candidate skills against job requirements (>= 2 core skills, or adjacent signal + >= 1 verified skill)
        has_adj_sig = any(sig in title_lower or sig in combined[:300] for sig in adj_signals)
        if overlap_count >= 2 or (has_adj_sig and overlap_count >= 1) or (
            has_adj_sig and target_industry in ("logistics_supply_chain", "finance_accounting", "marketing_growth", "sales_bd", "hr_recruiting", "public_admin_legal", "general_professional")
        ):
            return ("ADJACENT", matched_adj_role)

        # Entry-level non-internship roles matching candidate's academic field of study (for early-career candidates)
        is_entry_title = any(w in title_lower for w in ("junior", "entry", "trainee", "assistant", "უმცროს", "დამწყებ", "ასისტენტ"))
        if is_entry_title and eligible_internships and edu_tokens and any(tok in title_lower for tok in edu_tokens):
            return ("ADJACENT", "Education-Aligned Entry-Level Role")

        return ("NONE", f"Domain Gate: '{job_title}' does not align with candidate's CV skills or education.")

    def evaluate_job_tiered(
        self,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        current_status: str = "DISCOVERED",
        existing_rationale: str = "",
        portal: str = "custom",
        company: str = "",
    ) -> Dict[str, Any]:
        """
        Universal Multi-Tier Optimal Matching Algorithm:
        - Enforces Dynamic Person-Adaptive Experience Guard.
        - Categorizes matches into Tier 1 DIRECT, Tier 2 ADJACENT, and Tier 3 PUBLIC_INTERNSHIP (strictly separating state roles from private internships).
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

        raw_cand_years = parsed_skills.get("years_of_experience")
        candidate_years = float(raw_cand_years) if raw_cand_years is not None else 0.0
        raw_max_allowed = parsed_skills.get("max_allowed_years")
        # Normalize legacy stored 2.0 default when candidate_years is unstated (0.0 -> 1.0 yr entry ceiling)
        if raw_max_allowed is not None and raw_cand_years is None and float(raw_max_allowed) == 2.0:
            max_allowed: Optional[float] = 1.0
        else:
            max_allowed = float(raw_max_allowed) if raw_max_allowed is not None else None
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
        # MUST be 100% remote from Georgia unless the posting is explicitly located in Georgia (Tbilisi/Batumi/Kutaisi).
        if portal in ("djinni.co", "justjoin.it", "dou.ua") or portal.startswith("linkedin"):
            from .scrapers.base_scraper import evaluate_remote_and_language_gate
            cand_langs = parsed_skills.get("spoken_languages") or []
            td_low = f"{title}\n{description}".lower()
            is_local_ge = any(k in td_low for k in ("tbilisi", "batumi", "kutaisi", "თბილის", "ბათუმ", "ქუთაის", "საქართველო"))
            loc_hint = "Tbilisi, Georgia" if (portal.startswith("linkedin") and is_local_ge) else (
                "Remote" if portal in ("djinni.co", "justjoin.it", "dou.ua") else "International"
            )
            _, gate_status, gate_reason, _ = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text=loc_hint,
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
            company=company,
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
            elif skills_match_token(req, candidate_skills, cand_blob):
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
        target_ind = str(parsed_skills.get("target_industry") or "general_professional").lower()
        active_specialties = list(self.SPECIALIZED_PLATFORMS) + (
            self.TECH_ONLY_SPECIALTIES if target_ind in ("qa_tech", "software_engineering") else []
        )
        title_specialty_mismatch = any(
            re.search(r"\b" + re.escape(sp.lower()) + r"\b", title_lower) and sp.lower() not in cand_blob
            for sp in active_specialties
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

        is_pub_vacancy = is_public_sector_vacancy(portal, company=company, title=title, description=description)

        # Determine final Match Tier cleanly (Direct domain matches stay DIRECT even at 65-79% so e.g. ProCredit Junior QA is never mislabeled ADJACENT)
        if tier_hint == "PUBLIC_INTERNSHIP":
            final_tier = "PUBLIC_INTERNSHIP"
        elif tier_hint == "ADJACENT":
            final_tier = "ADJACENT"
        else:
            final_tier = "DIRECT"

        if final_tier == "ADJACENT":
            adjacent_tag = f"Adjacent Opportunity: {overlap_pct}% Skill Overlap ({tier_label})"
        elif is_pub_vacancy:
            adjacent_tag = "Public Sector Vacancy"
        elif final_tier == "PUBLIC_INTERNSHIP" or tier_label == "Entry-Level / Internship":
            adjacent_tag = "Entry-Level / Internship"
        else:
            adjacent_tag = None

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
        elif score >= 75.0 or (final_tier == "DIRECT" and score >= 72.0):
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
        elif is_pub_vacancy:
            rationale = f"Public Sector Vacancy ({score}% fit) | Matched: {matched_str}"
        elif final_tier == "PUBLIC_INTERNSHIP":
            rationale = f"Entry-Level & Graduate Internship ({score}% fit) | Matched: {matched_str}"
        elif tier_label == "Entry-Level / Internship":
            rationale = f"Entry-Level & Internship Match ({score}% fit) | Matched: {matched_str}"
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
