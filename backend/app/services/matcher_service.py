import json
import logging
import re
from typing import Dict, Any, List, Tuple
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
        for lang in ["English", "Georgian", "German", "Ukrainian", "Russian", "Spanish", "French", "ქართული", "ინგლისური"]:
            if lang.lower() in lower_text:
                normalized_lang = "Georgian" if lang == "ქართული" else ("English" if lang == "ინგლისური" else lang)
                if normalized_lang not in taxonomy["spoken_languages"]:
                    taxonomy["spoken_languages"].append(normalized_lang)
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
                canonical = skill_kw.title() if len(skill_kw) > 3 else skill_kw.upper()
                if skill_kw.lower() in lower_text and canonical not in all_skills:
                    all_skills.append(canonical)

        # Also extract bullet items under any ## Skills section
        in_skills = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("##"):
                in_skills = any(w in s.lower() for w in ["skill", "stack", "tech", "უნარ", "კომპეტენც"])
                continue
            if in_skills and s.startswith(("-", "*")):
                cleaned = re.sub(r"^[-*]\s*(\*\*.*?\*\*:?)?\s*", "", s)
                for part in re.split(r"[,;/]", cleaned):
                    p = part.strip()
                    if 1 < len(p) <= 45 and p not in all_skills:
                        all_skills.append(p)

        taxonomy["frameworks"] = list(dict.fromkeys(taxonomy["qa_automation"] + ["PyTest", "Playwright", "Cypress"]))
        taxonomy["tools"] = list(
            dict.fromkeys(taxonomy["api_and_performance"] + taxonomy["cicd_and_devops"] + ["Jira", "Git"])
        )
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
                canonical = skill_kw.title() if len(skill_kw) > 3 else skill_kw.upper()
                if skill_kw.lower() in combined and canonical not in required:
                    required.append(canonical)

        return required

    def validate_seniority_gate(
        self,
        candidate_years: float,
        candidate_seniority: str,
        job_title: str,
        job_description: str,
    ) -> Tuple[bool, str]:
        """
        Enforces strict seniority and experience boundaries:
        - If candidate has <= 2.5 years of experience (Junior to early Mid):
          * Immediately disqualifies "Senior", "Lead", "Principal", "Head of", "Staff", "Director", "Architect", "Sr."
          * Disqualifies jobs requiring > (candidate_years + 1.0) years of experience.
        - If candidate has <= 5.0 years:
          * Disqualifies "Principal", "Staff", "Head of", "Director", "Chief".
        Returns (is_allowed, reason).
        """
        combined = f"{job_title}\n{job_description}".lower()
        title_lower = job_title.lower()

        # Check job title for senior/lead level (English & Georgian)
        senior_lead_titles = [
            "lead", "principal", "head of", "staff", "director", "architect", "chief", "vp", "manager",
            "ლიდი", "ხელმძღვანელი", "დირექტორი", "მთავარი", "წამყვანი",
        ]
        senior_titles = ["senior", "sr.", "sr ", "უფროსი", "სინიორ"]

        # Extract explicit years of experience required by job
        job_req_years: Optional[float] = None
        yr_m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|წელი|წლიანი)(?:\s+of)?\s*(?:experience|გამოცდილება)?", combined)
        if yr_m:
            try:
                job_req_years = float(yr_m.group(1))
            except Exception:
                pass

        # Gate 1: Candidate is Junior or early Mid (<= 2.5 years)
        if candidate_years <= 2.5:
            for s in senior_lead_titles + senior_titles:
                pattern = r"\b" + re.escape(s) + r"\b"
                if re.search(pattern, title_lower):
                    return (
                        False,
                        f"Disqualified by Seniority Gate: Role requires {s.title()}, but candidate is Junior-Mid ({candidate_years:.1f} yrs exp).",
                    )
            if job_req_years is not None and job_req_years > (candidate_years + 1.0):
                return (
                    False,
                    f"Disqualified by Experience Gate: Role requires {job_req_years:g}+ years exp, exceeding candidate's {candidate_years:.1f} yrs.",
                )

        # Gate 2: Candidate is Mid level (2.5 to 5.0 years)
        elif candidate_years <= 5.0:
            for s in senior_lead_titles:
                pattern = r"\b" + re.escape(s) + r"\b"
                if re.search(pattern, title_lower):
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
    ) -> Tuple[bool, str]:
        """
        Enforces strict target-domain matching from CandidateProfile so generic or off-domain
        results (e.g., Backend Developer when searching QA, or Medical/Receptionist jobs
        when the candidate uploaded a QA skills.md) are rejected immediately.
        """
        target_industry = str(parsed_skills.get("target_industry") or "qa_tech").lower()
        title_lower = (job_title or "").lower()
        combined = f"{job_title}\n{job_description}".lower()

        if target_industry == "qa_tech":
            qa_title_signals = [
                "qa", "quality assurance", "quality engineer", "test", "tester",
                "sdet", "automation", "ტესტ", "ხარისხ",
            ]
            if any(sig in title_lower for sig in qa_title_signals):
                return (True, "Matches QA/Testing domain.")
            # If title doesn't mention QA/test, reject non-QA engineering/other postings
            return (
                False,
                f"Domain Gate: '{job_title}' does not match candidate's QA/Testing target profile.",
            )

        if target_industry == "receptionist_hospitality":
            hosp_signals = ["reception", "front desk", "hospitality", "concierge", "hotel", "guest", "მიმღებ", "რეცეფც", "სასტუმრ", "ადმინისტრატორ"]
            if any(sig in title_lower or sig in combined[:200] for sig in hosp_signals):
                return (True, "Matches Hospitality domain.")
            return (False, f"Domain Gate: '{job_title}' does not match Hospitality profile.")

        if target_industry == "healthcare_hospital":
            med_signals = ["medical", "hospital", "clinic", "patient", "სამედიცინო", "კლინიკ", "პაციენტ", "რეგისტრატორ"]
            if any(sig in title_lower or sig in combined[:200] for sig in med_signals):
                return (True, "Matches Healthcare domain.")
            return (False, f"Domain Gate: '{job_title}' does not match Healthcare profile.")

        if target_industry == "customer_service":
            cs_signals = ["support", "customer", "client", "call center", "helpdesk", "მხარდაჭერ", "ოპერატორ", "ქოლ"]
            if any(sig in title_lower or sig in combined[:200] for sig in cs_signals):
                return (True, "Matches Customer Support domain.")
            return (False, f"Domain Gate: '{job_title}' does not match Customer Support profile.")

        return (True, "Domain check passed.")

    def evaluate_job(
        self,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        current_status: str = "DISCOVERED",
        existing_rationale: str = "",
    ) -> Tuple[float, str, str, List[str], List[str]]:
        """
        Evaluates a job posting against CandidateProfile.parsed_skills.
        Returns:
          (suitability_score, new_status, match_rationale, matched_skills, missing_skills)
        - Preserves "FILTERED_OUT" if already filtered out by market/language gate.
        - Enforces Domain Gate & Seniority Gate: disqualifies off-domain or Senior/Lead roles.
        - Promotes listings with suitability_score >= 75.0 to "STAGED" ("Ready to Apply / Staging").
        """
        if current_status == "FILTERED_OUT":
            return (
                0.0,
                "FILTERED_OUT",
                existing_rationale or "Requires local language",
                [],
                [],
            )

        # Domain relevance validation
        dom_passed, dom_reason = self.validate_domain_gate(parsed_skills, title, description)
        if not dom_passed:
            return (
                0.0,
                "FILTERED_OUT",
                dom_reason,
                [],
                [],
            )

        # Seniority validation
        candidate_years = float(parsed_skills.get("years_of_experience") or 1.5)
        candidate_seniority = str(parsed_skills.get("seniority_level") or "JUNIOR")
        sen_passed, sen_reason = self.validate_seniority_gate(candidate_years, candidate_seniority, title, description)
        if not sen_passed:
            return (
                0.0,
                "FILTERED_OUT",
                sen_reason,
                [],
                [],
            )

        required_skills = self.extract_job_requirements(title, description)

        # Build candidate skill set from parsed_skills
        candidate_skills: List[str] = []
        for k in ["all_skills", "qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops", "tools", "frameworks"]:
            vals = parsed_skills.get(k, [])
            if isinstance(vals, list):
                for v in vals:
                    if str(v) not in candidate_skills:
                        candidate_skills.append(str(v))

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
            return (
                35.0,
                "FILTERED_OUT",
                f"Suitability Gate: Role requires specialized stack ({', '.join(missing_specialties or ['domain specialty'])}) not present in skills.md.",
                matched,
                missing,
            )

        if required_skills:
            raw_ratio = len(matched) / len(required_skills)
            # Penalize specialized platform gaps even in description
            penalty = 20.0 * len(missing_specialties)
            score = round(min(98.0, max(25.0, (raw_ratio * 78.0) + 22.0 - penalty)), 1)
        else:
            # Brief external-link listings without inline tech keywords: score by title alignment
            if any(w in title_lower for w in ["ავტომატიზაცი", "automation", "sdet"]) and has_automation_stack:
                score = 78.0
                matched = ["QA Automation"]
            elif any(w in title_lower for w in ["software qa", "qa engineer", "ტესტერ"]) and "report" not in title_lower and "რეპორტ" not in title_lower:
                # Training/beginner intern courses don't fit 1.5 yr automation profile unless general QA starter
                if any(w in desc_lower for w in ["სტაჟირების პროგრამა", "კურსი უკვე გაიარა", "course certificate"]):
                    score = 52.0
                else:
                    score = 65.0
            else:
                score = 45.0

        MIN_SUITABILITY_SCORE = 60.0

        if current_status in ("APPLIED", "REJECTED"):
            new_status = current_status
        elif score < MIN_SUITABILITY_SCORE:
            return (
                score,
                "FILTERED_OUT",
                f"Suitability Gate: {score}% match is below {int(MIN_SUITABILITY_SCORE)}% threshold for your skills.md (Missing: {', '.join(missing[:4]) or 'stack alignment'}).",
                matched,
                missing,
            )
        elif score >= 75.0:
            new_status = "STAGED"
        else:
            new_status = "AUDITED"

        matched_str = ", ".join(matched[:8]) if matched else "Role specialty alignment"
        missing_str = ", ".join(missing[:5]) if missing else "None (100% core requirement coverage)"
        queue_note = (
            "Auto-promoted to Ready to Apply / Staging queue (score >= 75%)."
            if new_status == "STAGED"
            else "Suitable match (60-74%): ready for targeted review."
        )
        rationale = (
            f"Suitability {score}% | Matched ({len(matched)}/{len(required_skills)}): {matched_str} | "
            f"Missing: {missing_str}. {queue_note}"
        )

        return (score, new_status, rationale, matched, missing)


matcher_service = MatcherService()
