import asyncio
from datetime import datetime, UTC
import logging
import re
import ssl
from typing import Dict, Any, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SHARED_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def get_shared_ssl_context() -> ssl.SSLContext:
    """Caches one default TLS context per process so concurrent httpx calls never stall reloading OS certs."""
    global _SHARED_SSL_CONTEXT
    if _SHARED_SSL_CONTEXT is None:
        _SHARED_SSL_CONTEXT = ssl.create_default_context()
    return _SHARED_SSL_CONTEXT

_UA_RU_MONTHS = {
    "січня": 1, "января": 1, "лютого": 2, "февраля": 2, "березня": 3, "марта": 3,
    "квітня": 4, "апреля": 4, "травня": 5, "мая": 5, "червня": 6, "июня": 6,
    "липня": 7, "июля": 7, "серпня": 8, "августа": 8, "вересня": 9, "сентября": 9,
    "жовтня": 10, "октября": 10, "листопада": 11, "ноября": 11, "грудня": 12, "декабря": 12,
}


def matches_domain_keywords(text: str, keywords: Optional[List[str]]) -> bool:
    """Word-boundary-safe multi-script keyword matcher (prevents 'qa' matching 'equal' or 'hr' matching 'three')."""
    if not keywords:
        return True
    low = (text or "").lower()
    if not low:
        return False
    for raw_kw in keywords:
        kw = str(raw_kw or "").strip().lower()
        if len(kw) < 2:
            continue
        if kw.isascii() and len(kw) <= 5 and kw.isalnum():
            if re.search(rf"\b{re.escape(kw)}\b", low):
                return True
        elif kw in low:
            return True
    return False


def parse_portal_published_at(raw_val: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """Parses ISO strings, Unix sec/ms epochs, or Slavic/English/Georgian dates into (utc_datetime, YYYY-MM-DD)."""
    if raw_val is None or raw_val == "":
        return None, None
    try:
        if isinstance(raw_val, int | float):
            ts = float(raw_val)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 1e8:
                dt = datetime.fromtimestamp(ts, tz=UTC)
                return dt, dt.date().isoformat()
        s = str(raw_val).strip()
        if not s:
            return None, None
        # ISO-8601 fast path (handles Z, fractional seconds, +00:00)
        iso_m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?", s)
        if iso_m:
            base = f"{iso_m.group(1)}T{iso_m.group(2) or '00:00:00'}+00:00"
            dt = datetime.fromisoformat(base)
            return dt, dt.date().isoformat()
        # Ukrainian / Russian day + month (e.g. "18 листопада", "5 ноября")
        sl_m = re.search(r"\b(\d{1,2})\s+([а-яіїєґё]+)(?:\s+(\d{4}))?", s.lower())
        if sl_m and sl_m.group(2) in _UA_RU_MONTHS:
            now = datetime.now(UTC)
            day, month = int(sl_m.group(1)), _UA_RU_MONTHS[sl_m.group(2)]
            year = int(sl_m.group(3)) if sl_m.group(3) else now.year
            dt = datetime(year, month, day, tzinfo=UTC)
            if not sl_m.group(3) and (dt - now).days > 45:
                dt = datetime(year - 1, month, day, tzinfo=UTC)
            return dt, dt.date().isoformat()
        from ..link_validator import parse_vacancy_published_date
        dt = parse_vacancy_published_date(s)
        if dt is not None:
            return dt, dt.date().isoformat()
    except Exception:
        pass
    return None, None

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
    is_url_like = lower.startswith(("http://", "https://", "www.")) or "linkedin.com" in lower
    has_blacklisted_sub = any(b in lower for b in _COMPANY_SUBSTRING_BLACKLIST)

    if cleaned and lower not in _COMPANY_LOCATION_BLACKLIST and not has_blacklisted_sub and not is_date_only and not is_url_like and len(cleaned) >= 2:
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


# Hybrid work mode patterns (English, Polish, Ukrainian, Russian)
HYBRID_WORK_PATTERNS = [
    # English hybrid work mode
    r"\bhybrid\s+(?:work|working|mode|model|role|job|schedule|position|policy|setup|option|environment|arrangement|contract|employment)\b",
    r"\b(?:work|working|model|mode|format|policy|schedule|workplace|employment|setup|arrangement)[\s:]+hybrid\b",
    r"\b(?:remote\s*[\/-]\s*hybrid|hybrid\s*[\/-]\s*remote|hybrid\s+remote)\b",
    r"\b(?:1|2|3|4)\s*days?\s*(?:a\s+week\s+)?(?:in|from|at)\s*(?:the\s+)?office\b",
    r"\b(?:in[\s-]office|office)\s*(?:1|2|3|4)\s*days?\b",
    r"\bpartially\s+remote\b",
    r"\bpart[\s-]time\s+remote\b",
    r"\bsemi[\s-]remote\b",
    r"\bcombination\s+of\s+(?:home|remote)\s+and\s+office\b",
    r"\bmix\s+of\s+(?:home|remote)\s+and\s+office\b",
    r"\b(?:flexible\s+)?hybrid\b",
    # Polish hybrid work mode
    r"\bhybrydow[a-zęóąśłżźć]*\b",
    r"\bhybryda\b",
    r"\bmodel\s+hybrydowy\b",
    r"\btryb\s+hybrydowy\b",
    r"\bpraca\s+hybrydowa\b",
    r"\bforma\s+pracy\s*:\s*hybrydow[a-zęóąśłżźć]*\b",
    r"\bczęściowo\s+zdalnie\b",
    r"\bczęściowo\s+zdalna\b",
    r"\b(?:1|2|3|4)\s*dn[ia|i]\s*(?:w\s+tygodniu\s+)?w\s+biurze\b",
    r"\bwymagana\s+obecność\s+w\s+biurze\b",
    # Ukrainian hybrid work mode
    r"\bгібрид\b",
    r"\bгібридн[а-яіїєґ]*\b",
    r"\bгібридний\s+формат\b",
    r"\bгібридний\s+режим\b",
    r"\bгібридний\s+графік\b",
    r"\bчастин[а-я]*\s+віддален[а-я]*\b",
    r"\b(?:1|2|3|4)\s*(?:дні|дня|днів)\s*(?:на\s+тиждень\s+)?в\s+офісі\b",
    r"\bробота\s+в\s+офісі\s+і\s+віддалено\b",
    # Russian hybrid work mode
    r"\bгибрид\b",
    r"\bгибридн[а-яё]*\b",
    r"\bгибридный\s+формат\b",
    r"\bгибридный\s+график\b",
    r"\bчастично\s+удален[а-яё]*\b",
    r"\b(?:1|2|3|4)\s*(?:дня|дней)\s*(?:в\s+неделю\s+)?в\s+офисе\b",
]

# On-site / Office work mode patterns
ONSITE_WORK_PATTERNS = [
    # English onsite/office
    r"\bon-?site\s+only\b",
    r"\bonsite\s+only\b",
    r"\boffice\s+only\b",
    r"\bonly\s+office\b",
    r"\bon-?site\b",
    r"\bin-?office\b",
    r"\boffice-?based\b",
    r"\bwork\s+(?:only\s+)?from\s+(?:the\s+)?office\b",
    r"\bwork\s+in\s+the\s+office\b",
    r"\bmust\s+work\s+from\s+(?:the\s+|our\s+)?office\b",
    r"\boffice\s+presence\s+required\b",
    r"\bno\s+remote\b",
    r"\bnot\s+remote\b",
    r"\bnot\s+open\s+to\s+remote\b",
    r"\b100%?\s*(?:on-?site|in-?office|office)\b",
    r"\bworkplace\s*:\s*(?:on-?site|office|stacjonarna)\b",
    # Polish onsite/office
    r"\bstacjonarn[a-zęóąśłżźć]*\b",
    r"\bpraca\s+stacjonarna\b",
    r"\btryb\s+stacjonarny\b",
    r"\bforma\s+pracy\s*:\s*stacjonarna\b",
    r"\bw\s+biurze\b",
    r"\btylko\s+w\s+biurze\b",
    r"\btylko\s+stacjonarnie\b",
    r"\bwymagana\s+praca\s+w\s+biurze\b",
    # Ukrainian onsite/office
    r"\bтільки\s+офіс\b",
    r"\bтільки\s+в\s+офісі\b",
    r"\bробота\s+в\s+офісі\b",
    r"\bофісн[а-яіїєґ]*\s+робота\b",
    r"\bне\s+віддален[а-я]*\b",
    r"\bбез\s+віддален[а-я]*\b",
    # Russian onsite/office
    r"\bтолько\s+офис\b",
    r"\bтолько\s+в\s+офисе\b",
    r"\bработа\s+в\s+офисе\b",
    r"\bофисн[а-яё]*\s+работа\b",
    r"\bне\s+удален[а-яё]*\b",
    r"\bбез\s+удаленк[а-яё]*\b",
]

# Genuine full remote patterns
FULL_REMOTE_PATTERNS = [
    r"\b(?:100%|full[\s-]time|fully|strictly)\s*remote\b",
    r"\b100%?\s*zdalnie\b",
    r"\bcałkowicie\s+zdalnie\b",
    r"\bpełna\s+praca\s+zdalna\b",
    r"\b100%?\s*віддалено\b",
    r"\bповністю\s+віддалено\b",
    r"\bтільки\s+віддалено\b",
    r"\b100%?\s*удаленно\b",
    r"\bполностью\s+удаленно\b",
    r"\bтолько\s+удаленно\b",
    r"\bworldwide\b",
    r"\bglobal\s+remote\b",
    r"\bwork\s+from\s+anywhere\b",
    r"\bremote\s+worldwide\b",
    r"\bremote\s+first\b",
    r"\banywhere\b",
    r"\bzdalnie\b",
    r"\bвіддалено\b",
    r"\bудаленно\b",
    r"\bдистанционн[а-яё]*\b",
    r"\bremote\b",
]

_TECH_HYBRID_PATTERN = re.compile(
    r"\bhybrid\s+(?:cloud|app|apps|application|applications|mobile|testing|framework|infrastructure|network|architecture|solution)\b",
    re.IGNORECASE,
)

_US_GEORGIA_STATE_RE = re.compile(
    r"(?:\b(?:atlanta|savannah|augusta|marietta|alpharetta|roswell|macon|united\s+states|u\.s\.a?)\b|georgia,\s*(?:us|usa|united\s+states)\b|,\s*ga\b|\bga,\s*(?:us|usa)\b)",
    re.IGNORECASE,
)


def is_georgia_country_location(loc_lower: str) -> bool:
    """Distinguishes the country of Georgia (Tbilisi/Batumi/საქართველო) from the US state of Georgia (Atlanta, GA)."""
    text = (loc_lower or "").lower()
    if any(
        w in text
        for w in (
            "tbilisi", "batumi", "kutaisi", "rustavi",
            "თბილისი", "ბათუმი", "ქუთაისი", "საქართველო",
            "тбилиси", "батуми", "кутаиси", "рустави", "грузия",
        )
    ):
        return True
    if "georgia" in text and not _US_GEORGIA_STATE_RE.search(text):
        return True
    return False


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
    - Strict Foreign Remote Gate: ANY vacancy from a foreign portal (Djinni, JustJoin, DOU, LinkedIn outside GE)
      MUST be 100% Remote. Any hybrid or on-site role requiring physical presence abroad is disqualified.
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
    loc_lower = (location_text or "").lower()
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

    # Detect hybrid work mode
    has_hybrid_loc = any(re.search(pat, loc_lower, re.IGNORECASE) for pat in HYBRID_WORK_PATTERNS)
    has_hybrid_body = any(re.search(pat, body_only, re.IGNORECASE) for pat in HYBRID_WORK_PATTERNS)
    if has_hybrid_body and not has_hybrid_loc:
        hybrid_matches = list(re.finditer(r"\bhybrid\b", body_only, re.IGNORECASE))
        tech_matches = list(_TECH_HYBRID_PATTERN.finditer(body_only))
        if hybrid_matches and len(hybrid_matches) == len(tech_matches):
            has_hybrid_body = False
    is_hybrid = has_hybrid_loc or has_hybrid_body

    # Detect on-site work mode
    has_onsite_loc = any(re.search(pat, loc_lower, re.IGNORECASE) for pat in ONSITE_WORK_PATTERNS)
    has_onsite_body = any(re.search(pat, body_only, re.IGNORECASE) for pat in ONSITE_WORK_PATTERNS)
    is_onsite = has_onsite_loc or has_onsite_body

    # Detect full remote eligibility (remote-only portals default to remote unless explicit hybrid/onsite)
    has_remote = any(re.search(pat, combined, re.IGNORECASE) for pat in FULL_REMOTE_PATTERNS) or (
        portal in ("remotive.com", "himalayas.app", "remoteok.com") and not is_onsite and not is_hybrid
    )

    is_georgia_location = is_georgia_country_location(loc_lower)
    is_domestic_portal = portal in ("jobs.ge", "hr.ge", "hr.gov.ge") or (portal == "headhunter.ge" and is_georgia_location)
    is_foreign_portal_or_job = not is_domestic_portal and not (portal in ("jobs.ge", "hr.ge", "hr.gov.ge") or is_georgia_location)

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
    is_us_location = bool(_US_GEORGIA_STATE_RE.search(loc_lower)) or any(
        re.search(rf"\b{state}\b", loc_lower) for state in [
            "united states", "usa", "u.s.", "san francisco", "new york", "austin", "chicago",
            "seattle", "los angeles", "california", "texas", "washington", "boston", "ny", "ca", "tx", "wa", "ga"
        ]
    )
    is_worldwide_remote = any(
        w in combined for w in [
            "worldwide", "work from anywhere", "anywhere in the world",
            "global remote", "remote worldwide", "remote - emea", "remote (europe)",
            "remote (eu)", "b2b contractor", "contractor worldwide", "remote (georgia)"
        ]
    )

    if (portal == "linkedin.com" or "linkedin" in portal) and (has_us_legal_restriction or (is_us_location and not is_georgia_location and not is_worldwide_remote)):
        return (
            False,
            "FILTERED_OUT",
            "Location Gate: US-based position (requires US residency / work authorization; not open to remote from Georgia)",
            langs_detected,
        )

    # 1. STRICT FOREIGN PORTAL / WORK-MODE GATE:
    # Foreign vacancies (Djinni, JustJoin, DOU, LinkedIn non-GE, etc.) MUST be 100% Remote.
    # Hybrid or On-site positions requiring foreign physical presence MUST be filtered out.
    if is_foreign_portal_or_job:
        if is_hybrid:
            return (
                False,
                "FILTERED_OUT",
                "Location/Work-Mode Gate: Foreign vacancy is Hybrid (requires physical office attendance abroad; only 100% Remote positions accepted)",
                langs_detected,
            )
        if is_onsite:
            return (
                False,
                "FILTERED_OUT",
                "Location/Work-Mode Gate: Foreign vacancy is On-site (requires physical presence abroad; only 100% Remote positions accepted)",
                langs_detected,
            )
        if not has_remote:
            return (
                False,
                "FILTERED_OUT",
                "Location/Work-Mode Gate: Foreign vacancy is not Remote (requires physical presence abroad; only 100% Remote positions accepted)",
                langs_detected,
            )

    is_remote = has_remote and not is_onsite and not is_hybrid

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
                "Location/Work-Mode Gate: Foreign vacancy is not Remote (requires physical presence abroad; only 100% Remote positions accepted)",
                langs_detected,
            )

    return (True if is_foreign_portal_or_job else is_remote, "DISCOVERED", "", langs_detected)


def classify_georgia_b2b_suitability(
    *,
    title: str = "",
    description: str = "",
    location_text: str = "",
    portal: str = "generic",
    market: str = "GLOBAL_REMOTE",
    salary_currency: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classifies whether a vacancy fits a Georgia-based job seeker locally (GEL / Tbilisi / Georgia)
    or remotely from Georgia via an international B2B / Independent Contractor arrangement (UTC+4).
    """
    p_low = (portal or "").lower()
    m_up = (market or "").upper()
    blob = f"{title} {location_text} {description[:2500]}".lower()

    ge_local_portals = {"jobs.ge", "hr.ge", "hr.gov.ge", "headhunter.ge"}
    if p_low in ge_local_portals or m_up in ("GE_DOMESTIC", "GE_PUBLIC") or (salary_currency or "").upper() == "GEL":
        is_remote_flag = bool(re.search(r"\b(remote|დისტანციურ|სახლიდან|hybrid)\b", blob))
        return {
            "contract_mode": "GE_LOCAL",
            "georgia_eligible": True,
            "b2b_ready": bool(is_remote_flag or "b2b" in blob or "contract" in blob),
            "eligibility_note": "Georgian Local Market (GEL / Labor or Contractor)",
        }

    # Check explicit foreign residency / work-authorization hard locks
    hard_region_locks = [
        r"\bus[\s-]only\b",
        r"\bunited states only\b",
        r"\bmust be (?:located|based|resident) in (?:the )?(?:us|usa|canada|uk|eu|germany|poland)\b",
        r"\bauthorized to work in the (?:us|united states|uk|canada)\b",
        r"\bus citizenship required\b",
        r"\bus citizen required\b",
        r"\bno visa sponsorship\b.*\bus citizens?\b",
        r"\bw-?2 only\b",
    ]
    explicit_ge_or_worldwide = bool(
        is_georgia_country_location(blob)
        or re.search(
            r"\b(worldwide|anywhere|global remote|work from anywhere|emea|europe|caucasus|utc\+?4|gmt\+?4)\b",
            blob,
        )
    )
    if any(re.search(pat, blob) for pat in hard_region_locks) and not explicit_ge_or_worldwide:
        return {
            "contract_mode": "REGION_LOCKED",
            "georgia_eligible": False,
            "b2b_ready": False,
            "eligibility_note": "Residency or local work permit restriction detected",
        }

    is_b2b_signal = bool(
        re.search(
            r"\b(b2b|contractor|freelance|independent contractor|consultant|eur|usd|worldwide|emea|europe|remote)\b",
            blob,
        )
    ) or m_up in ("GLOBAL_REMOTE", "INT_REMOTE", "EU_REMOTE")
    return {
        "contract_mode": "REMOTE_B2B",
        "georgia_eligible": True,
        "b2b_ready": is_b2b_signal,
        "eligibility_note": "Remote B2B Eligible from Georgia (UTC+4 / Independent Contractor)",
    }


class BasePortalScraper:
    portal_name: str = "custom"
    market: str = "GLOBAL_REMOTE"
    rate_limit_delay_sec: float = 0.05
    max_retries: int = 2
    _host_semaphores: Dict[str, asyncio.Semaphore] = {}

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
    }

    @classmethod
    def _get_host_semaphore(cls, url: str) -> asyncio.Semaphore:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "default").lower()
        sem = cls._host_semaphores.get(host)
        if sem is None:
            sem = asyncio.Semaphore(4)
            cls._host_semaphores[host] = sem
        return sem

    async def _request_with_backoff(
        self,
        url: str,
        *,
        timeout: float = 6.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[httpx.Response]:
        merged_headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        sem = self._get_host_semaphore(url)
        for attempt in range(1, self.max_retries + 1):
            try:
                async with sem:
                    if self.rate_limit_delay_sec > 0:
                        await asyncio.sleep(self.rate_limit_delay_sec)
                    async with httpx.AsyncClient(
                        headers=merged_headers,
                        follow_redirects=True,
                        timeout=timeout,
                        verify=get_shared_ssl_context(),
                    ) as client:
                        response = await client.get(url)
                if response.status_code == 200:
                    return response
                if response.status_code in (401, 403, 404):
                    logger.debug("[%s] HTTP %d on %s — skipping retry", self.portal_name, response.status_code, url)
                    return None
                if response.status_code in (429, 503) and attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After", "")
                    wait_s = min(3.0, float(retry_after)) if retry_after.isdigit() else min(2.5, 0.6 * attempt)
                    await asyncio.sleep(wait_s)
                    continue
                logger.debug("[%s] HTTP %d on %s (attempt %d)", self.portal_name, response.status_code, url, attempt)
            except Exception as e:
                logger.debug("[%s] Network fetch attempt %d failed for %s: %s", self.portal_name, attempt, url, e)
        return None

    async def fetch_html(self, url: str, timeout: float = 4.0) -> Optional[str]:
        """Fetches HTML from a URL with per-host concurrency limiting and bounded 429/503 backoff."""
        resp = await self._request_with_backoff(url, timeout=timeout)
        return resp.text if (resp is not None and resp.text) else None

    async def fetch_json(
        self,
        url: str,
        timeout: float = 8.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """Fetches JSON payload with shared backoff, rate limiting, and safe parsing."""
        req_headers = {"Accept": "application/json", **(headers or {})}
        resp = await self._request_with_backoff(url, timeout=timeout, headers=req_headers)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception as exc:
            logger.debug("[%s] Invalid JSON from %s: %s", self.portal_name, url, exc)
            return None

    def make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        """No synthetic/hardcoded fallback vacancies; live scraped results only."""
        return []

    async def scrape_and_enrich_urls(
        self,
        urls: List[str],
        parse_fn,
        enrich_fn,
        *,
        limit: int = 20,
        dedupe_key: str = "external_id",
        dedupe_title_company: bool = False,
        keep_filtered_stubs: bool = False,
        page_timeout: float = 8.0,
        sort_newest_first: bool = False,
    ) -> List[Dict[str, Any]]:
        """Shared fetch -> parse -> dedupe -> concurrent enrichment pipeline for HTML portal scrapers."""
        pages = await asyncio.gather(*(self.fetch_html(u, timeout=page_timeout) for u in urls), return_exceptions=True)
        candidates: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        seen_tc: set[Tuple[str, str]] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in parse_fn(html):
                    key = str(item.get(dedupe_key) or "")
                    tc = (str(item.get("title") or "").lower().strip(), str(item.get("company") or "").lower().strip())
                    if key and key in seen_keys:
                        continue
                    if dedupe_title_company and tc in seen_tc:
                        continue
                    if key:
                        seen_keys.add(key)
                    if dedupe_title_company:
                        seen_tc.add(tc)
                    candidates.append(item)
        if not candidates:
            return []
        if sort_newest_first:
            candidates.sort(
                key=lambda c: c["published_at"].timestamp() if c.get("published_at") else 0.0,
                reverse=True,
            )
        if keep_filtered_stubs:
            to_enrich = [c for c in candidates if c.get("status") != "FILTERED_OUT"][:limit]
            filtered_stubs = [c for c in candidates if c.get("status") == "FILTERED_OUT"]
        else:
            to_enrich = candidates[:limit]
            filtered_stubs = []
        results: List[Dict[str, Any]] = []
        if to_enrich:
            enriched = await asyncio.gather(*(enrich_fn(c) for c in to_enrich), return_exceptions=True)
            results.extend(x for x in enriched if isinstance(x, dict))
        results.extend(filtered_stubs)
        return results

    async def scrape(self, allow_network: bool = True) -> List[Dict[str, Any]]:
        raise NotImplementedError
