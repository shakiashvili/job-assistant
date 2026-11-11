import asyncio
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_COMPANY_LOCATION_BLACKLIST = {
    "საქართველოს მასშტაბით",
    "მთელი საქართველო",
    "თბილისი",
    "ბათუმი",
    "ქუთაისი",
    "რუსთავი",
    "გორი",
    "ზუგდიდი",
    "თელავი",
    "დისტანციურად",
    "დისტანციური",
    "tbilisi",
    "batumi",
    "kutaisi",
    "georgia",
    "remote",
    "worldwide",
    "georgian employer",
    "hr.ge verified employer",
    "employer",
    "employer (hr.ge)",
    "company",
}


def sanitize_company_name(
    raw_company: Optional[str],
    target_email: Optional[str] = None,
    fallback: str = "Hiring Company",
) -> str:
    """Rejects location strings (e.g. 'საქართველოს მასშტაბით') mistakenly scraped as employer names."""
    cleaned = re.sub(r"\s+", " ", (raw_company or "")).strip(" -|•·,")
    lower = cleaned.lower()
    is_date_only = bool(re.match(r"^\d{1,2}\s+[ა-ჰa-z]+$", lower))
    if cleaned and lower not in _COMPANY_LOCATION_BLACKLIST and not is_date_only and len(cleaned) >= 2:
        return cleaned

    if target_email and "@" in target_email:
        domain_root = target_email.split("@", 1)[1].split(".")[0].strip()
        if domain_root.lower() not in ("gmail", "yahoo", "mail", "outlook", "hotmail", "icloud", "proton", "hr", "jobs"):
            return domain_root.upper() if len(domain_root) <= 3 else domain_root.capitalize()

    return fallback


# Mandatory Strict Language Gate Keywords (Ukrainian / Russian requirement indicators)
SLAVIC_LANGUAGE_REQUIREMENT_PATTERNS = [
    r"вільно",
    r"українськ",
    r"русский",
    r"русском",
    r"разговорн",
    r"на разговорном уровне",
    r"fluent ukrainian",
    r"native ukrainian",
    r"ukrainian required",
    r"ukrainian is a must",
    r"fluent russian",
    r"native russian",
    r"russian required",
    r"знання української",
    r"рівень української",
    r"співбесіда українською",
]


def parse_contact_method_and_email(text: str, html: str = "") -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parses the application submission channel ("WEB_FORM", "EMAIL", "EXTERNAL_LINK"),
    target email address (e.g. hr@bank.ge), and required email subject line format from job text/HTML.
    """
    combined = f"{text}\n{html}"
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", combined)
    target_email = email_match.group(0) if email_match else None

    subject_line = None
    subj_match = re.search(
        r"(?:subject(?:\s+line)?|სათაურის\s+ველში|თემა)\s*[:\-–]?\s*[\"“']([^\"”'\n]{3,80})[\"”']",
        combined,
        re.IGNORECASE,
    )
    if subj_match:
        subject_line = subj_match.group(1).strip()

    if target_email:
        return ("EMAIL", target_email, subject_line)

    if "apply" in combined.lower() or "<form" in html.lower():
        return ("WEB_FORM", None, None)

    return ("EXTERNAL_LINK", None, None)


POLISH_LANGUAGE_REQUIREMENT_PATTERNS = [
    r"język polski",
    r"języka polskiego",
    r"wymagany polski",
    r"bardzo dobra znajomość języka polskiego",
    r"poszukujemy",
    r"doświadczenia",
    r"umowa o pracę",
    r"długofalowa współpraca",
    r"polski wymagany",
]


def evaluate_remote_and_language_gate(
    title: str,
    description: str,
    location_text: str = "Remote",
    portal: str = "dou.ua",
) -> Tuple[bool, str, str, List[str]]:
    """
    Evaluates a scraped vacancy against the Mandatory Remote & Local-Language Gate:
    Returns:
      (is_remote, status, filter_out_reason, detected_languages)
    - For dou.ua / djinni.co / justjoin.it:
      1. Vacancies must allow remote work / relocation.
      2. Checks title + actual job description (excluding portal UI city metadata) for
         mandatory Ukrainian, Russian, or Polish fluency requirements.
      3. Only accepts positions where English is the working language.
    """
    body_only = f"{title}\n{description}".lower()
    combined = f"{title}\n{description}\n{location_text}".lower()
    langs_detected: List[str] = []

    if any(w in combined for w in ["english", "upper-intermediate", "b2", "c1", "fluent english", "spoken english"]):
        langs_detected.append("English")

    has_slavic_keyword = any(re.search(pat, body_only, re.IGNORECASE) for pat in SLAVIC_LANGUAGE_REQUIREMENT_PATTERNS)
    has_polish_keyword = any(re.search(pat, body_only, re.IGNORECASE) for pat in POLISH_LANGUAGE_REQUIREMENT_PATTERNS)

    # Measure Cyrillic density on actual job title + body (NOT portal Ukrainian city metadata lists)
    cyrillic_chars = len(re.findall(r"[а-яА-ЯіїєґІЇЄҐ]", f"{title}\n{description}"))
    polish_diacritics = len(re.findall(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", f"{title}\n{description}"))

    if cyrillic_chars > 35 or has_slavic_keyword:
        if any(w in body_only for w in ["україн", "ukrainian", "вільно"]) or re.search(r"[іїєґІЇЄҐ]", description):
            langs_detected.append("Ukrainian")
        if any(w in body_only for w in ["русск", "russian", "разговорн"]):
            langs_detected.append("Russian")
        if "Ukrainian" not in langs_detected and "Russian" not in langs_detected:
            langs_detected.append("Ukrainian")

    if portal == "justjoin.it" and (has_polish_keyword or polish_diacritics >= 12):
        langs_detected.append("Polish")

    if not langs_detected:
        langs_detected.append("English")

    is_office_only = any(
        w in combined for w in ["office only", "on-site only", "onsite only", "тільки офіс", "only office", "stacjonarnie"]
    )
    is_remote = not is_office_only and any(
        w in combined for w in ["remote", "віддалено", "zdalnie", "relocate", "relocation", "anywhere", "worldwide", "abroad", "tbilisi", "georgia"]
    )

    loc_lower = (location_text or "").lower()
    ukraine_restricted = (
        "(ukraine)" in title.lower()
        or "ukraine-based role" in combined
        or "located in ukraine" in combined
        or "ukraine only" in combined
        or "only ukraine" in combined
        or "office in the center of lviv" in combined
        or "office in lviv" in combined
        or "office in kyiv" in combined
        or ("ukraine" in loc_lower and not any(w in loc_lower for w in ["worldwide", "europe", "eu", "global", "abroad", "georgia", "relocat", "other countries", "віддалено"]))
    )

    if portal in ("dou.ua", "djinni.co", "justjoin.it"):
        if has_slavic_keyword or "Ukrainian" in langs_detected or "Russian" in langs_detected:
            return (
                is_remote,
                "FILTERED_OUT",
                "Mandatory local Slavic language requirement (Requires local language)",
                langs_detected,
            )
        if "Polish" in langs_detected and "english" not in body_only:
            return (
                is_remote,
                "FILTERED_OUT",
                "Mandatory Polish language requirement (Requires local language)",
                langs_detected,
            )
        if "Polish" in langs_detected and polish_diacritics >= 15:
            return (
                is_remote,
                "FILTERED_OUT",
                "Job description written in Polish (Requires local language)",
                langs_detected,
            )
        if ukraine_restricted and not ("global remote" in combined or "remote worldwide" in combined):
            return (
                False,
                "FILTERED_OUT",
                "Location Gate: Restricted to Ukraine-based candidates",
                langs_detected,
            )
        if not is_remote:
            return (
                False,
                "FILTERED_OUT",
                "Not Remote / Relocation eligible",
                langs_detected,
            )

    return (is_remote, "DISCOVERED", "", langs_detected)


class BasePortalScraper:
    portal_name: str = "custom"
    market: str = "GLOBAL_REMOTE"
    rate_limit_delay_sec: float = 0.25
    max_retries: int = 2

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
    }

    async def fetch_html(self, url: str, timeout: float = 6.0) -> Optional[str]:
        """Fetches HTML from a URL with polite concurrency rate limiting and retry logic."""
        for attempt in range(1, self.max_retries + 1):
            try:
                await asyncio.sleep(self.rate_limit_delay_sec)
                async with httpx.AsyncClient(
                    headers=self.DEFAULT_HEADERS,
                    follow_redirects=True,
                    timeout=timeout,
                ) as client:
                    response = await client.get(url)
                    if response.status_code == 200 and response.text:
                        return response.text
                    logger.warning(
                        f"[{self.portal_name}] HTTP {response.status_code} on {url} (attempt {attempt})"
                    )
            except Exception as e:
                logger.debug(f"[{self.portal_name}] Network fetch attempt {attempt} failed for {url}: {e}")
        return None

    def make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    async def scrape(self, allow_network: bool = True) -> List[Dict[str, Any]]:
        raise NotImplementedError
