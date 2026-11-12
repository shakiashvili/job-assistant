import json
import logging
import re
from typing import Dict, Any, Optional, Tuple
from ..config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


class SalaryService:
    """
    Automated AI Salary Estimator:
    1. Extracts explicit salary ranges via regex from the job description (salary_estimated_by_ai = False).
    2. When unstated, estimates fair market salary range using Gemini 2.5 Flash (with calibrated market
       model fallback) based on role seniority, geographic market (GE vs UA_REMOTE / INT_REMOTE),
       and tech stack demands (Playwright + Python automation vs manual QA, etc.).
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
                logger.warning(f"SalaryService Gemini init fallback: {e}")

    def extract_explicit_salary(self, text: str) -> Optional[Tuple[float, float, str]]:
        """
        Extracts explicit salary mentions from text such as:
        - "$3,000 - $4,500", "$4,200 – $5,500"
        - "5000-7000 GEL", "2,200 – 2,800 GEL", "3500 ₾"
        - "€40k - €55k", "€40k", "€6,500 - €8,000"
        - "$4500/mo", "USD 4000 - 5500"
        """
        if not text:
            return None

        # Normalize dashes
        norm = text.replace("–", "-").replace("—", "-")

        # 1. Currency symbol prefix range: $3,000 - $4,500 or €6,500 - €8,000 or €40k - €50k
        sym_range = re.search(
            r"([\$€£₾])\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?\s*-\s*[\$€£₾]?\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?",
            norm
        )
        if sym_range:
            sym, v1, k1, v2, k2 = sym_range.groups()
            cur = {"$": "USD", "€": "EUR", "£": "GBP", "₾": "GEL"}.get(sym, "USD")
            low = float(v1.replace(",", "")) * (1000.0 if (k1 or k2) and float(v1.replace(",", "")) < 500 else 1.0)
            high = float(v2.replace(",", "")) * (1000.0 if k2 and float(v2.replace(",", "")) < 500 else 1.0)
            if low >= 300 and high >= low:
                return (round(low, 2), round(high, 2), cur)

        # 2. Number range followed by currency code: 5000-7000 GEL, 3,000 - 4,500 USD, 2,200 - 2,800 GEL
        code_range = re.search(
            r"\b(\d[\d,]*(?:\.\d+)?)\s*([kK])?\s*-\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?\s*(USD|EUR|GEL|GBP|ლარი|₾)\b",
            norm,
            re.IGNORECASE,
        )
        if code_range:
            v1, k1, v2, k2, code = code_range.groups()
            cur = "GEL" if code.lower() in ("gel", "ლარი", "₾") else code.upper()
            low = float(v1.replace(",", "")) * (1000.0 if (k1 or k2) and float(v1.replace(",", "")) < 500 else 1.0)
            high = float(v2.replace(",", "")) * (1000.0 if k2 and float(v2.replace(",", "")) < 500 else 1.0)
            if low >= 300 and high >= low:
                return (round(low, 2), round(high, 2), cur)

        # 3. Currency code prefix range: USD 3,000 - 4,500 / GEL 4000 - 5500
        prefix_code_range = re.search(
            r"\b(USD|EUR|GEL|GBP)\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?\s*-\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?",
            norm,
            re.IGNORECASE,
        )
        if prefix_code_range:
            code, v1, k1, v2, k2 = prefix_code_range.groups()
            cur = code.upper()
            low = float(v1.replace(",", "")) * (1000.0 if (k1 or k2) and float(v1.replace(",", "")) < 500 else 1.0)
            high = float(v2.replace(",", "")) * (1000.0 if k2 and float(v2.replace(",", "")) < 500 else 1.0)
            if low >= 300 and high >= low:
                return (round(low, 2), round(high, 2), cur)

        # 4. Prefix single cap/floor values: "to $700", "up to $2,500", "from $1500"
        prefix_single = re.search(
            r"\b(?:up\s+to|to|from|от|до)\s*([\$€£₾])\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])?\b",
            norm,
            re.IGNORECASE,
        )
        if prefix_single:
            sym, val, has_k = prefix_single.groups()
            cur = {"$": "USD", "€": "EUR", "£": "GBP", "₾": "GEL"}.get(sym, "USD")
            base = float(val.replace(",", "")) * (1000.0 if has_k else 1.0)
            if base >= 250:
                return (round(base, 2), round(base, 2), cur)

        # 5. Single value with k or explicit currency: €40k, $4,500 / mo, $700, 5000 GEL
        single_sym = re.search(
            r"([\$€£₾])\s*(\d[\d,]*(?:\.\d+)?)\s*([kK])\b",
            norm
        )
        if single_sym:
            sym, val, _ = single_sym.groups()
            cur = {"$": "USD", "€": "EUR", "£": "GBP", "₾": "GEL"}.get(sym, "USD")
            base = float(val.replace(",", "")) * 1000.0
            if base >= 250:
                return (round(base * 0.9, 2), round(base * 1.1, 2), cur)

        single_mo = re.search(
            r"([\$€£₾])\s*(\d{1,2},\d{3}|\d{3,6})\b",
            norm
        )
        if single_mo:
            sym, val = single_mo.groups()
            cur = {"$": "USD", "€": "EUR", "£": "GBP", "₾": "GEL"}.get(sym, "USD")
            base = float(val.replace(",", ""))
            if base >= 250:
                return (base, base, cur)

        single_code = re.search(
            r"\b(\d{1,2},\d{3}|\d{3,6})\s*(GEL|USD|EUR|GBP|ლარი)\b",
            norm,
            re.IGNORECASE
        )
        if single_code:
            val, code = single_code.groups()
            cur = "GEL" if code.lower() in ("gel", "ლარი", "₾") else code.upper()
            base = float(val.replace(",", ""))
            if base >= 500:
                return (base, base, cur)

        return None

    def _detect_seniority(self, title: str, description: str) -> str:
        combined = f"{title} {description}".lower()
        if any(w in combined for w in ["lead", "principal", "staff", "head of", "architect", "manager"]):
            return "Lead"
        if any(w in combined for w in ["senior", "sr.", "sr ", "5+ years", "4+ years"]):
            return "Senior"
        if any(w in combined for w in ["junior", "jr.", "intern", "trainee", "entry"]):
            return "Junior"
        return "Middle"

    def extract_vacancy_salary(
        self,
        title: str,
        description: str,
    ) -> Dict[str, Any]:
        """
        Extracts salary ONLY when explicitly stated in the vacancy title or description.
        Never fabricates estimated USD/GEL numbers when a posting omits compensation or is unpaid.
        """
        combined_text = f"{title}\n{description}"
        lower = combined_text.lower()
        explicit = self.extract_explicit_salary(combined_text)
        if explicit:
            min_sal, max_sal, currency = explicit
            return {
                "min_salary": min_sal,
                "max_salary": max_sal,
                "currency": currency,
                "salary_estimated_by_ai": False,
                "is_unpaid": False,
                "confidence_score": 0.96,
                "seniority_detected": self._detect_seniority(title, description),
                "rationale": f"Extracted explicit salary ({min_sal:g} - {max_sal:g} {currency}) directly from job description.",
            }

        is_unpaid = any(
            kw in lower
            for kw in [
                "არ ითვალისწინებს ანაზღაურებას",
                "ანაზღაურების გარეშე",
                "unpaid internship",
                "unpaid position",
                "no compensation",
            ]
        )
        return {
            "min_salary": None,
            "max_salary": None,
            "currency": None,
            "salary_estimated_by_ai": False,
            "is_unpaid": is_unpaid,
            "confidence_score": 1.0 if is_unpaid else 0.0,
            "seniority_detected": self._detect_seniority(title, description),
            "rationale": (
                "Unpaid internship program (explicitly noted in job description)."
                if is_unpaid
                else "Salary not specified in job description."
            ),
        }

    def estimate_salary(
        self,
        title: str,
        description: str,
        market: str = "INT_REMOTE",
        portal: str = "generic",
    ) -> Dict[str, Any]:
        """
        Determines salary range for a job posting without asking the user:
        - First checks explicit regex mentions in title + description.
        - Otherwise estimates via Gemini 2.5 Flash or calibrated market estimator.
        """
        combined_text = f"{title}\n{description}"
        explicit = self.extract_explicit_salary(combined_text)
        if explicit:
            min_sal, max_sal, currency = explicit
            return {
                "min_salary": min_sal,
                "max_salary": max_sal,
                "currency": currency,
                "salary_estimated_by_ai": False,
                "confidence_score": 0.96,
                "seniority_detected": self._detect_seniority(title, description),
                "rationale": f"Extracted explicit salary ({min_sal:g} - {max_sal:g} {currency}) directly from job description.",
            }

        seniority = self._detect_seniority(title, description)
        lower_desc = combined_text.lower()
        is_automation_sdet = any(
            k in lower_desc for k in ["playwright", "cypress", "selenium", "sdet", "automation", "pytest", "python", "k6"]
        )

        # Try live Gemini estimation if API key is configured
        if self.client:
            try:
                from google.genai import types
                prompt = f"""Estimate the fair monthly market salary range for this role.
Role Title: {title}
Seniority: {seniority}
Geographic Market: {market} (Portal: {portal})
Tech Stack / Description: {description[:1500]}

Return JSON with keys:
- min_salary (number, monthly)
- max_salary (number, monthly)
- currency ("GEL" for Georgian domestic market GE, "USD" for UA_REMOTE or INT_REMOTE, or "EUR" for EU)
- confidence_score (float 0.0 to 1.0)
- rationale (short 1-sentence explanation)
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
                    parsed = json.loads(resp.text)
                    return {
                        "min_salary": float(parsed.get("min_salary", 3000)),
                        "max_salary": float(parsed.get("max_salary", 4500)),
                        "currency": str(parsed.get("currency", "USD")),
                        "salary_estimated_by_ai": True,
                        "confidence_score": float(parsed.get("confidence_score", 0.85)),
                        "seniority_detected": seniority,
                        "rationale": str(parsed.get("rationale", "Estimated by Gemini 2.5 Flash market model.")),
                    }
            except Exception as e:
                logger.warning(f"Gemini salary estimation fallback triggered: {e}")

        # Calibrated Market Benchmark Model (Monthly Compensation)
        market_upper = (market or "INT_REMOTE").upper()
        if market_upper == "GE" or portal in ("jobs.ge", "hr.ge"):
            currency = "GEL"
            # Georgian domestic market benchmarks (in GEL / month)
            base_ranges = {
                "Junior": (2000.0, 3000.0),
                "Middle": (4000.0, 6000.0),
                "Senior": (6500.0, 9500.0),
                "Lead": (8500.0, 12000.0),
            }
            low, high = base_ranges.get(seniority, (4000.0, 6000.0))
            if not is_automation_sdet:
                low = round(low * 0.72, -2)
                high = round(high * 0.75, -2)
        elif market_upper == "UA_REMOTE" or portal in ("dou.ua", "djinni.co"):
            currency = "USD"
            base_ranges = {
                "Junior": (1200.0, 1800.0),
                "Middle": (2500.0, 3600.0),
                "Senior": (4200.0, 5600.0),
                "Lead": (5200.0, 6800.0),
            }
            low, high = base_ranges.get(seniority, (2800.0, 4000.0))
            if not is_automation_sdet:
                low = round(low * 0.78, -2)
                high = round(high * 0.80, -2)
        else:
            currency = "USD"
            base_ranges = {
                "Junior": (2200.0, 3200.0),
                "Middle": (3800.0, 5200.0),
                "Senior": (5500.0, 7500.0),
                "Lead": (7000.0, 9500.0),
            }
            low, high = base_ranges.get(seniority, (4000.0, 5500.0))
            if not is_automation_sdet:
                low = round(low * 0.80, -2)
                high = round(high * 0.82, -2)

        stack_label = "QA Automation / SDET (Playwright/Python)" if is_automation_sdet else "General QA / Specialist"
        return {
            "min_salary": float(low),
            "max_salary": float(high),
            "currency": currency,
            "salary_estimated_by_ai": True,
            "confidence_score": 0.84,
            "seniority_detected": seniority,
            "rationale": (
                f"AI-estimated {seniority} {stack_label} range for {market_upper} market "
                f"({low:g} - {high:g} {currency}/mo)."
            ),
        }


salary_service = SalaryService()
