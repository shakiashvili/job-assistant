import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup
from .portal_detector import detect_portal_from_url

logger = logging.getLogger(__name__)

# Georgian month names mapping (nominative, dative, genitive)
GEORGIAN_MONTHS = {
    "იანვარი": 1, "თებერვალი": 2, "მარტი": 3, "აპრილი": 4, "მაისი": 5, "ივნისი": 6,
    "ივლისი": 7, "აგვისტო": 8, "სექტემბერი": 9, "ოქტომბერი": 10, "ნოემბერი": 11, "დეკემბერი": 12,
    "იანვარს": 1, "თებერვალს": 2, "მარტს": 3, "აპრილს": 4, "მაისს": 5, "ივნისს": 6,
    "ივლისს": 7, "აგვისტოს": 8, "სექტემბერს": 9, "ოქტომბერს": 10, "ნოემბერს": 11, "დეკემბერს": 12,
    "იანვრის": 1, "თებერვლის": 2, "მარტის": 3, "აპრილის": 4, "მაისის": 5, "ივნისის": 6,
    "ივლისის": 7, "აგვისტოს": 8, "სექტემბრის": 9, "ოქტომბრის": 10, "ნოემბრის": 11, "დეკემბრის": 12,
}

ENGLISH_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DEADLINE_KW_PATTERN = (
    r"(?:ბოლო\s*ვადა|განცხადების\s*ვადა|ვადა|"
    r"deadline|valid\s+until|closing\s+date|apply\s+before|apply\s+by|"
    r"submit\s+before|submit\s+by|due\s+date|expires?(?:\s+on)?)"
)
_MONTH_WORD_PATTERN = r"[A-Za-z\u10A0-\u10FF\u1C90-\u1CBF]+"


def _build_deadline_tuple(
    year: int,
    month: int,
    day: int,
    display_str: str,
    today: date,
) -> Optional[Tuple[datetime, str, bool]]:
    try:
        dl_date = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dl_date, display_str, dl_date.date() < today


def _resolve_month_number(token: str) -> Optional[int]:
    cleaned = token.strip(".,").lower()
    return ENGLISH_MONTHS.get(cleaned) or GEORGIAN_MONTHS.get(cleaned)


def parse_vacancy_deadline(text: str) -> Tuple[Optional[datetime], Optional[str], bool]:
    """
    Parses application deadline dates from vacancy text (English, Georgian, and ISO formats).
    Returns (deadline_datetime, deadline_display_string, is_expired).
    If no deadline is explicitly mentioned, returns (None, None, False).
    """
    if not text:
        return None, None, False

    today = datetime.now(timezone.utc).date()

    # Pattern 1: Georgian numeric "ბოლო ვადა: DD.MM.YYYY" or "DD/MM/YYYY" or "DD-MM-YYYY"
    for m1 in re.finditer(r"(?:ბოლო\s*ვადა|განცხადების\s*ვადა|ვადა)\s*[:—–-]?\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", text, re.I):
        day, month, year = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
        if year < 100:
            year += 2000
        res = _build_deadline_tuple(year, month, day, f"{day:02d}.{month:02d}.{year}", today)
        if res:
            return res

    # Pattern 2: English "Deadline: DD.MM.YYYY" or "Valid until: YYYY-MM-DD"
    for m2 in re.finditer(
        r"(?:deadline|valid\s+until|closing\s+date|apply\s+before|apply\s+by|submit\s+before|submit\s+by|due\s+date|expires?(?:\s+on)?)\s*(?:is|[:—–-])?\s*(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})",
        text,
        re.I,
    ):
        p1, p2, p3 = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        if p1 > 1000:  # YYYY-MM-DD
            year, month, day = p1, p2, p3
        else:  # DD.MM.YYYY
            day, month, year = p1, p2, p3
            if month > 12 >= day:  # Handle MM/DD/YYYY safely when day > 12
                day, month = month, day
            if year < 100:
                year += 2000
        res = _build_deadline_tuple(year, month, day, f"{year}-{month:02d}-{day:02d}", today)
        if res:
            return res

    # Pattern 3a: Day-first named months e.g. "Apply before 15 January 2024" or "ბოლო ვადა: 25 ნოემბერი 2026"
    day_first_re = (
        rf"{_DEADLINE_KW_PATTERN}\s*(?:is|[:—–-])?\s*"
        rf"(\d{{1,2}})(?:st|nd|rd|th)?[\s,.-]+({_MONTH_WORD_PATTERN})[\s,.-]+(\d{{4}})\b"
    )
    for m3a in re.finditer(day_first_re, text, re.I):
        day = int(m3a.group(1))
        month_raw = m3a.group(2)
        year = int(m3a.group(3))
        month = _resolve_month_number(month_raw)
        if month:
            res = _build_deadline_tuple(year, month, day, f"{day} {month_raw.capitalize()} {year}", today)
            if res:
                return res

    # Pattern 3b: Month-first named months e.g. "Deadline: November 25, 2026"
    month_first_re = (
        rf"{_DEADLINE_KW_PATTERN}\s*(?:is|[:—–-])?\s*"
        rf"({_MONTH_WORD_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,|\s)+\s*(\d{{4}})\b"
    )
    for m3b in re.finditer(month_first_re, text, re.I):
        month_raw = m3b.group(1)
        day = int(m3b.group(2))
        year = int(m3b.group(3))
        month = _resolve_month_number(month_raw)
        if month:
            res = _build_deadline_tuple(year, month, day, f"{month_raw.capitalize()} {day}, {year}", today)
            if res:
                return res

    return None, None, False


_PUBLISHED_KW_PATTERN = r"(?:გამოქვეყნდა|თარიღი|published(?:\s+on)?|posted(?:\s+on)?|date\s+posted)"


def _infer_year_for_day_month(day: int, month: int, today: date) -> Optional[datetime]:
    year = today.year
    try:
        dt = datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)
    except ValueError:
        return None
    if dt.date() > today + timedelta(days=7):
        try:
            dt = datetime(year - 1, month, day, 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            return None
    return dt


def parse_vacancy_published_date(
    text: str,
    *,
    standalone: bool = False,
) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parses a vacancy's publication date from either a dedicated date cell/value (standalone=True)
    or a full vacancy description containing labels like 'გამოქვეყნდა: 24 ნოემბერი' or 'Published: 2026-11-24'.
    Returns (published_datetime_utc, display_string).
    """
    raw = (text or "").strip()
    if not raw:
        return None, None

    today = datetime.now(timezone.utc).date()

    # 1. Epoch timestamp (int/float seconds or ms)
    if standalone and re.fullmatch(r"\d{10,13}", raw):
        ts = int(raw)
        if ts > 10_000_000_000:
            ts = ts // 1000
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")
        except Exception:
            return None, None

    # 2. ISO date/datetime (e.g. 2026-11-24 or 2026-11-24T09:15:00Z)
    iso_pat = r"(20\d{2})-(\d{2})-(\d{2})" if standalone else rf"{_PUBLISHED_KW_PATTERN}\s*[:—–-]?\s*(20\d{{2}})-(\d{{2}})-(\d{{2}})"
    m_iso = re.search(iso_pat, raw, re.I)
    if m_iso:
        try:
            dt = datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)), 12, 0, 0, tzinfo=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 3. Relative words (standalone or labeled)
    low = raw.lower()
    if standalone:
        if low in ("today", "დღეს", "just now", "new"):
            dt = datetime(today.year, today.month, today.day, 12, 0, 0, tzinfo=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")
        if low in ("yesterday", "გუშინ"):
            yd = today - timedelta(days=1)
            dt = datetime(yd.year, yd.month, yd.day, 12, 0, 0, tzinfo=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")
        rel_m = re.search(r"(\d{1,2})\s*(?:days?|d|დღის)\s*(?:ago|წინ)?", low)
        if rel_m:
            d = today - timedelta(days=int(rel_m.group(1)))
            dt = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")

    # 4. Numeric DD.MM.YYYY / DD/MM/YYYY
    num_pat = r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b" if standalone else rf"{_PUBLISHED_KW_PATTERN}\s*[:—–-]?\s*(\d{{1,2}})[./-](\d{{1,2}})[./-](\d{{2,4}})"
    m_num = re.search(num_pat, raw, re.I)
    if m_num:
        day, month, year = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if year < 100:
            year += 2000
        try:
            dt = datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)
            return dt, dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 5. Day + Georgian/English month (+ optional year), e.g. "24 ნოემბერი" or "გამოქვეყნდა: 24 ნოემბერი 2026"
    dm_pat = (
        rf"\b(\d{{1,2}})[\s,.-]+({_MONTH_WORD_PATTERN})(?:[\s,.-]+(20\d{{2}}))?\b"
        if standalone
        else rf"{_PUBLISHED_KW_PATTERN}\s*[:—–-]?\s*(\d{{1,2}})[\s,.-]+({_MONTH_WORD_PATTERN})(?:[\s,.-]+(20\d{{2}}))?"
    )
    m_dm = re.search(dm_pat, raw, re.I)
    if m_dm:
        day = int(m_dm.group(1))
        month = _resolve_month_number(m_dm.group(2))
        yr_raw = m_dm.group(3)
        if month:
            if yr_raw:
                try:
                    dt = datetime(int(yr_raw), month, day, 12, 0, 0, tzinfo=timezone.utc)
                    return dt, dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
            else:
                dt = _infer_year_for_day_month(day, month, today)
                if dt:
                    return dt, dt.strftime("%Y-%m-%d")

    # 6. Month + Day (+ optional year), e.g. "Nov 24, 2026"
    md_pat = (
        rf"\b({_MONTH_WORD_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:[\s,]+(20\d{{2}}))?\b"
        if standalone
        else rf"{_PUBLISHED_KW_PATTERN}\s*[:—–-]?\s*({_MONTH_WORD_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:[\s,]+(20\d{{2}}))?"
    )
    m_md = re.search(md_pat, raw, re.I)
    if m_md:
        month = _resolve_month_number(m_md.group(1))
        day = int(m_md.group(2))
        yr_raw = m_md.group(3)
        if month:
            if yr_raw:
                try:
                    dt = datetime(int(yr_raw), month, day, 12, 0, 0, tzinfo=timezone.utc)
                    return dt, dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
            else:
                dt = _infer_year_for_day_month(day, month, today)
                if dt:
                    return dt, dt.strftime("%Y-%m-%d")

    return None, None


def validate_live_html_content(url: str, html: str) -> Tuple[bool, str]:
    """
    Inspects fetched HTML content to verify that the vacancy page is active and NOT blank/expired.
    Specifically prevents blank 200 OK skeleton pages (like expired Jobs.ge pages where
    'დასახელება:' and 'მომწოდებელი:' cells are empty).
    Returns (is_valid_content, extracted_clean_text).
    """
    if not html or len(html.strip()) < 120:
        return False, ""

    soup = BeautifulSoup(html, "html.parser")
    portal_type = detect_portal_from_url(url)

    # Check common expired/404 page text
    full_text = soup.get_text(" ", strip=True)
    lower_text = full_text.lower()
    expired_phrases = [
        "вакансію видалено",
        "вакансію закрито",
        "ვაკანსია ვერ მოიძებნა",
        "განცხადება წაშლილია",
        "განცხადება ვერ მოიძებნა",
        "no longer accepting applications",
        "this job is no longer available",
        "job not found",
        "vacancy not found",
    ]
    if any(p in lower_text for p in expired_phrases):
        return False, ""

    if portal_type == "jobs.ge":
        dtable = soup.select_one(".dtable")
        if not dtable:
            return False, ""

        dtable_text = dtable.get_text(" ", strip=True)
        # Verify title and company cells are not empty
        title_populated = False
        company_populated = False
        for tr in dtable.find_all("tr"):
            row_text = tr.get_text(" ", strip=True)
            if "დასახელება:" in row_text or "Title:" in row_text:
                val = re.sub(r"^(?:დასახელება|Title)\s*:\s*", "", row_text).strip()
                if len(val) >= 2:
                    title_populated = True
            if "მომწოდებელი:" in row_text or "Employer:" in row_text or "Company:" in row_text:
                val = re.sub(r"^(?:მომწოდებელი|Employer|Company)\s*:\s*", "", row_text).strip()
                if len(val) >= 2:
                    company_populated = True

        # Strip boilerplate header labels to verify there is actual announcement content
        cleaned_check = re.sub(
            r"(?:დასახელება|მომწოდებელი|გამოქვეყნდა|ბოლო\s*ვადა|ყველა\s*ვაკანსია|ამოსაბეჭდი\s*ვერსია|Title|Published|Deadline)[:/|]*",
            "",
            dtable_text,
        ).strip()
        if not title_populated or not company_populated or len(cleaned_check) < 40:
            return False, ""

        return True, dtable_text

    if portal_type == "djinni.co":
        desc_el = soup.select_one("div.job-post__description, div[id^='job-description-'], main")
        txt = desc_el.get_text(" ", strip=True) if desc_el else full_text
        if len(txt) < 80:
            return False, ""
        return True, txt[:4000]

    if portal_type == "dou.ua":
        desc_el = soup.select_one("div.b-vacancy, div.vacancy-section, div.l-vacancy")
        txt = desc_el.get_text(" ", strip=True) if desc_el else full_text
        if len(txt) < 80:
            return False, ""
        return True, txt[:4000]

    if portal_type == "hr.ge":
        if len(full_text) < 150:
            return False, ""
        main_el = soup.select_one("main, div.announcement-details, div.container")
        txt = main_el.get_text(" ", strip=True) if main_el else full_text
        return True, txt[:4000]

    return len(full_text) >= 80, full_text[:4000]


async def fetch_and_validate_live_vacancy(url: str, timeout: float = 4.0) -> Tuple[bool, str, str]:
    """
    Performs an asynchronous HTTP GET request to a vacancy URL and verifies:
    1. Every URL and redirect hop passes SSRF validation (fail closed).
    2. HTTP status code is 200 OK.
    3. Response HTML contains non-empty, active vacancy content (discarding blank/expired pages).
    Returns (is_live_and_valid, extracted_clean_text, raw_html).
    """
    if not url or not url.strip():
        return False, "", ""

    import urllib.parse
    from .audit_service import validate_safe_external_url

    clean_url = url.strip()
    if any(d in clean_url for d in ["example.com", "fakejob.ge", "testportal.local", "dummy"]):
        return False, "", ""

    try:
        validate_safe_external_url(clean_url, require_dns=True)
    except ValueError as ssrf_err:
        logger.warning(f"Blocked unsafe vacancy link {clean_url}: {ssrf_err}")
        return False, "", ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
    }

    try:
        current_url = clean_url
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
            resp = None
            for _ in range(5):
                validate_safe_external_url(current_url, require_dns=True)
                resp = await client.get(current_url)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if not location:
                        return False, "", ""
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                break
            if resp is None or resp.status_code != 200 or not resp.text:
                code = resp.status_code if resp is not None else "no-response"
                logger.info(f"Vacancy link rejected (HTTP {code}): {clean_url}")
                return False, "", ""

            is_valid, clean_text = validate_live_html_content(current_url, resp.text)
            if not is_valid:
                logger.info(f"Vacancy link rejected (blank/expired HTML body): {clean_url}")
                return False, "", ""

            return True, clean_text, resp.text
    except ValueError as ssrf_err:
        logger.warning(f"Blocked unsafe redirect on vacancy link {clean_url}: {ssrf_err}")
        return False, "", ""
    except Exception as e:
        logger.debug(f"Live GET health check failed for {clean_url}: {e}")
        return False, "", ""


async def verify_vacancy_liveness(url: str, timeout: float = 8.0) -> bool:
    """
    Verifies via real-time HTTP GET check that a vacancy URL returns 200 OK
    AND contains active non-blank announcement content.
    """
    is_valid, _, _ = await fetch_and_validate_live_vacancy(url, timeout=timeout)
    return is_valid


async def validate_urls_batch(
    urls: List[str],
    concurrency: int = 5,
    timeout: float = 8.0,
) -> Dict[str, Tuple[bool, str, str]]:
    """Checks multiple vacancy URLs concurrently bounded by asyncio.Semaphore(concurrency)."""
    sem = asyncio.Semaphore(max(1, concurrency))
    results: Dict[str, Tuple[bool, str, str]] = {}

    async def _check_one(u: str) -> None:
        async with sem:
            results[u] = await fetch_and_validate_live_vacancy(u, timeout=timeout)

    unique_urls = list(dict.fromkeys(u for u in urls if u))
    if unique_urls:
        await asyncio.gather(*(_check_one(u) for u in unique_urls), return_exceptions=True)
    return results
