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
    "ამ ორგანიზაციის ყველა განცხადება",
    "ყველა ვაკანსია",
    "ამოსაბეჭდი ვერსია",
    "all announcements of this organization",
    "printable version",
    "all vacancies",
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
    "employer (jobs.ge)",
    "company",
    "კომპანია (jobs.ge)",
    "კომპანია (hr.ge)",
}

_COMPANY_SUBSTRING_BLACKLIST = [
    "ამ ორგანიზაციის ყველა განცხადება",
    "ყველა განცხადება",
    "ყველა ვაკანსია",
    "ამოსაბეჭდი ვერსია",
    "საქართველოს მასშტაბით",
    "all announcements of this",
    "all vacancies",
    "printable version",
    "hr.ge verified employer",
    "verified employer",
]


def sanitize_company_name(
    raw_company: Optional[str],
    target_email: Optional[str] = None,
    fallback: str = "Hiring Company",
) -> str:
    """Rejects location strings (e.g. 'საქართველოს მასშტაბით') and portal chrome mistakenly scraped as employer names."""
    cleaned = re.sub(r"\s+", " ", (raw_company or "")).strip(" -|•·,")
    lower = cleaned.lower()
    is_date_only = bool(re.match(r"^\d{1,2}\s+[ა-ჰa-z]+$", lower))
    has_blacklisted_sub = any(b in lower for b in _COMPANY_SUBSTRING_BLACKLIST)

    if cleaned and lower not in _COMPANY_LOCATION_BLACKLIST and not has_blacklisted_sub and not is_date_only and len(cleaned) >= 2:
        return cleaned

    if target_email and "@" in target_email:
        domain_root = target_email.split("@", 1)[1].split(".")[0].strip()
        if domain_root.lower() not in ("gmail", "yahoo", "mail", "outlook", "hotmail", "icloud", "proton", "hr", "jobs", "example"):
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
    candidate_languages: Optional[List[str]] = None,
) -> Tuple[bool, str, str, List[str]]:
    """
    Evaluates a scraped vacancy against the Remote & Spoken-Language Gate:
    Returns:
      (is_remote, status, filter_out_reason, detected_languages)
    - Supports dynamic unlocking via `candidate_languages` from `skills.md`:
      If the vacancy requires Ukrainian, Russian, or Polish, allow it when the candidate
      explicitly lists that language in `skills.md`; otherwise filter it out.
    """
    cand_norm = {str(c).lower().strip() for c in (candidate_languages or ["English", "Georgian"])}
    knows_ukrainian = any(k in cand_norm for k in ("ukrainian", "uk", "ua", "українська", "უკრაინული"))
    knows_russian = any(k in cand_norm for k in ("russian", "ru", "русский", "რუსული"))
    knows_polish = any(k in cand_norm for k in ("polish", "pl", "polski", "польский", "პოლონური"))

    body_only = f"{title}\n{description}".lower()
    combined = f"{title}\n{description}\n{location_text}".lower()
    langs_detected: List[str] = []

    if any(w in combined for w in ["english", "upper-intermediate", "b2", "c1", "fluent english", "spoken english"]):
        langs_detected.append("English")

    has_slavic_keyword = any(re.search(pat, body_only, re.IGNORECASE) for pat in SLAVIC_LANGUAGE_REQUIREMENT_PATTERNS)
    has_polish_keyword = any(re.search(pat, body_only, re.IGNORECASE) for pat in POLISH_LANGUAGE_REQUIREMENT_PATTERNS)

    # Measure Cyrillic & Polish density on actual job title + body (NOT portal UI city chrome)
    cyrillic_chars = len(re.findall(r"[а-яА-ЯіїєґІЇЄҐ]", f"{title}\n{description}"))
    polish_diacritics = len(re.findall(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", f"{title}\n{description}"))

    has_uk_markers = bool(
        re.search(r"[іїєґІЇЄҐ]", description)
        or any(w in body_only for w in ["україн", "ukrainian", "вільно", "досвід", "вимоги", "тестуван"])
    )
    has_ru_markers = bool(
        re.search(r"[ыэъёЫЭЪЁ]", f"{title}\n{description}")
        or any(w in body_only for w in ["русск", "russian", "разговорн", "опыт", "знание", "требования", "тестировани"])
    )

    if cyrillic_chars > 35 or has_slavic_keyword:
        if has_uk_markers:
            langs_detected.append("Ukrainian")
        if has_ru_markers or (portal == "headhunter.ge" and not has_uk_markers and cyrillic_chars > 35):
            langs_detected.append("Russian")
        if "Ukrainian" not in langs_detected and "Russian" not in langs_detected:
            langs_detected.append("Russian" if portal == "headhunter.ge" else "Ukrainian")

    if portal == "justjoin.it" and (has_polish_keyword or polish_diacritics >= 12):
        langs_detected.append("Polish")

    if not langs_detected:
        langs_detected.append("English")

    is_office_only = any(
        w in combined for w in ["office only", "on-site only", "onsite only", "тільки офіс", "только офис", "only office", "stacjonarnie"]
    )
    is_remote = not is_office_only and any(
        w in combined for w in ["remote", "віддалено", "удален", "удалён", "zdalnie", "relocate", "relocation", "anywhere", "worldwide", "abroad", "tbilisi", "georgia"]
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

    is_georgia_location = any(w in loc_lower for w in ["georgia", "tbilisi", "batumi", "kutaisi", "თბილისი", "საქართველო"])
    is_worldwide_remote = any(
        w in combined for w in [
            "worldwide", "work from anywhere", "anywhere in the world",
            "global remote", "remote worldwide", "remote - emea", "remote (europe)",
            "remote (eu)", "b2b contractor", "contractor worldwide", "remote (georgia)"
        ]
    )

    # Disqualify US-only vacancies or vacancies requiring US work authorization / residency
    has_us_legal_restriction = any(
        w in combined for w in [
            "must be legally authorized to work in the united states",
            "us citizen", "green card", "u.s. citizen", "w2 only", "no c2c",
            "must reside in the united states", "us only", "usa only",
            "authorized to work in the us", "work authorization in the united states",
            "no visa sponsorship"
        ]
    )
    is_us_location = any(
        re.search(rf"\b{state}\b", loc_lower) for state in [
            "united states", "usa", "u.s.", "san francisco", "new york", "austin", "chicago",
            "seattle", "los angeles", "california", "texas", "washington", "boston", "ny", "ca", "tx", "wa"
        ]
    )

    if (portal == "linkedin.com" or "linkedin" in portal) and (has_us_legal_restriction or (is_us_location and not is_georgia_location and not is_worldwide_remote)):
        return (
            False,
            "FILTERED_OUT",
            "Location Gate: US-based position (requires US residency / work authorization; not open to remote from Georgia)",
            langs_detected,
        )

    if portal in ("dou.ua", "djinni.co", "justjoin.it", "headhunter.ge"):
        requires_uk = "Ukrainian" in langs_detected
        requires_ru = "Russian" in langs_detected
        requires_pl = "Polish" in langs_detected and ("english" not in body_only or polish_diacritics >= 15)

        if requires_uk and not knows_ukrainian and not (requires_ru and knows_russian):
            return (
                is_remote,
                "FILTERED_OUT",
                "Mandatory Ukrainian language requirement (Requires local language — add Ukrainian in skills.md to unlock)",
                langs_detected,
            )
        if requires_ru and not knows_russian and not (requires_uk and knows_ukrainian):
            return (
                is_remote,
                "FILTERED_OUT",
                "Mandatory Russian language requirement (Requires local language — add Russian in skills.md to unlock)",
                langs_detected,
            )
        if requires_pl and not knows_polish:
            return (
                is_remote,
                "FILTERED_OUT",
                "Mandatory Polish language requirement (Requires local language — add Polish in skills.md to unlock)",
                langs_detected,
            )
        if portal != "headhunter.ge" and ukraine_restricted and not ("global remote" in combined or "remote worldwide" in combined):
            return (
                False,
                "FILTERED_OUT",
                "Location Gate: Restricted to Ukraine-based candidates",
                langs_detected,
            )
        if portal in ("dou.ua", "djinni.co", "justjoin.it") and not is_remote:
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
    rate_limit_delay_sec: float = 0.05
    max_retries: int = 2

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
    }

    async def fetch_html(self, url: str, timeout: float = 4.5) -> Optional[str]:
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
