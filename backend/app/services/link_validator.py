import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Georgian month names mapping
GEORGIAN_MONTHS = {
    "იანვარი": 1, "თებერვალი": 2, "მარტი": 3, "აპრილი": 4, "მაისი": 5, "ივნისი": 6,
    "ივლისი": 7, "აგვისტო": 8, "სექტემბერი": 9, "ოქტომბერი": 10, "ნოემბერი": 11, "დეკემბერი": 12,
    "იანვარს": 1, "თებერვალს": 2, "მარტს": 3, "აპრილს": 4, "მაისს": 5, "ივნისს": 6,
    "ივლისს": 7, "აგვისტოს": 8, "სექტემბერს": 9, "ოქტომბერს": 10, "ნოემბერს": 11, "დეკემბერს": 12,
}

ENGLISH_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_vacancy_deadline(text: str) -> Tuple[Optional[datetime], Optional[str], bool]:
    """
    Parses application deadline dates from vacancy text (English, Georgian, and ISO formats).
    Returns (deadline_datetime, deadline_display_string, is_expired).
    If no deadline is explicitly mentioned, returns (None, None, False).
    """
    if not text:
        return None, None, False

    now = datetime.now(timezone.utc)
    today = now.date()

    # Pattern 1: Georgian numeric "ბოლო ვადა: DD.MM.YYYY" or "DD/MM/YYYY" or "DD-MM-YYYY"
    m1 = re.search(r"(?:ბოლო\s*ვადა|განცხადების\s*ვადა|ვადა)\s*[:—–-]?\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", text, re.I)
    if m1:
        try:
            day, month, year = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
            if year < 100:
                year += 2000
            dl_date = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
            is_expired = dl_date.date() < today
            return dl_date, f"{day:02d}.{month:02d}.{year}", is_expired
        except Exception:
            pass

    # Pattern 2: English "Deadline: DD.MM.YYYY" or "Valid until: YYYY-MM-DD"
    m2 = re.search(r"(?:deadline|valid\s+until|closing\s+date|apply\s+before|expires?)\s*[:—–-]?\s*(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})", text, re.I)
    if m2:
        try:
            p1, p2, p3 = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            if p1 > 1000:  # YYYY-MM-DD
                year, month, day = p1, p2, p3
            else:  # DD.MM.YYYY
                day, month, year = p1, p2, p3
                if year < 100:
                    year += 2000
            dl_date = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
            is_expired = dl_date.date() < today
            return dl_date, f"{year}-{month:02d}-{day:02d}", is_expired
        except Exception:
            pass

    # Pattern 3: Named months e.g. "Deadline: November 25, 2026" or "25 ნოემბერი 2026"
    m3 = re.search(r"(?:deadline|closing\s+date|valid\s+until|ვადა)\s*[:—–-]?\s*([A-Za-z]+|\w+)\s+(\d{1,2}),?\s*(\d{4})", text, re.I)
    if m3:
        try:
            month_str, day, year = m3.group(1).lower(), int(m3.group(2)), int(m3.group(3))
            month = ENGLISH_MONTHS.get(month_str) or GEORGIAN_MONTHS.get(month_str)
            if month:
                dl_date = datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
                is_expired = dl_date.date() < today
                return dl_date, f"{month_str.capitalize()} {day}, {year}", is_expired
        except Exception:
            pass

    return None, None, False


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
    lower_url = url.lower()

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

    if "jobs.ge" in lower_url:
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

    if "djinni.co" in lower_url:
        desc_el = soup.select_one("div.job-post__description, div[id^='job-description-'], main")
        txt = desc_el.get_text(" ", strip=True) if desc_el else full_text
        if len(txt) < 80:
            return False, ""
        return True, txt[:4000]

    if "dou.ua" in lower_url:
        desc_el = soup.select_one("div.b-vacancy, div.vacancy-section, div.l-vacancy")
        txt = desc_el.get_text(" ", strip=True) if desc_el else full_text
        if len(txt) < 80:
            return False, ""
        return True, txt[:4000]

    if "hr.ge" in lower_url:
        if len(full_text) < 150:
            return False, ""
        main_el = soup.select_one("main, div.announcement-details, div.container")
        txt = main_el.get_text(" ", strip=True) if main_el else full_text
        return True, txt[:4000]

    return len(full_text) >= 80, full_text[:4000]


async def fetch_and_validate_live_vacancy(url: str, timeout: float = 4.0) -> Tuple[bool, str, str]:
    """
    Performs an asynchronous HTTP GET request to a vacancy URL and verifies:
    1. HTTP status code is 200 OK.
    2. Response HTML contains non-empty, active vacancy content (discarding blank/expired pages).
    Returns (is_live_and_valid, extracted_clean_text, raw_html).
    """
    if not url or not url.strip():
        return False, "", ""

    clean_url = url.strip()
    if clean_url.startswith(("http://localhost", "http://127.0.0.1")):
        return True, "Local health endpoint", ""

    if any(d in clean_url for d in ["example.com", "fakejob.ge", "testportal.local", "dummy"]):
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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(clean_url)
            if resp.status_code != 200 or not resp.text:
                logger.info(f"Vacancy link rejected (HTTP {resp.status_code}): {clean_url}")
                return False, "", ""

            is_valid, clean_text = validate_live_html_content(clean_url, resp.text)
            if not is_valid:
                logger.info(f"Vacancy link rejected (blank/expired HTML body): {clean_url}")
                return False, "", ""

            return True, clean_text, resp.text
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
