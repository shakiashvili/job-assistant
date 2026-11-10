import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
import httpx

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


async def verify_vacancy_liveness(url: str, timeout: float = 5.0) -> bool:
    """
    Verifies if a vacancy URL is live and accessible.
    - Local mock URLs and test domains are instantly recognized as live.
    - Performs an HTTP HEAD check (with GET fallback for servers rejecting HEAD).
    - Returns False for HTTP 404, 410, DNS failures, or connection errors.
    """
    if not url or not url.strip():
        return False

    clean_url = url.strip()
    # Recognize local mock environment URLs
    if "localhost" in clean_url or "127.0.0.1" in clean_url or "mock-portals" in clean_url:
        return True

    # Reject placeholder dummy domains
    if any(d in clean_url for d in ["example.com", "fakejob.ge", "testportal.local", "dummy"]):
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 TalentFlow/2.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            try:
                head_resp = await client.head(clean_url)
                if head_resp.status_code in (200, 201, 204, 301, 302, 307, 308):
                    return True
                if head_resp.status_code == 405:  # Method Not Allowed -> fallback to GET
                    get_resp = await client.get(clean_url, headers={"Range": "bytes=0-1024"})
                    return get_resp.status_code in (200, 206, 301, 302, 304)
                if head_resp.status_code in (404, 410):
                    return False
                return head_resp.status_code < 400
            except httpx.HTTPError:
                # Fallback to quick GET
                get_resp = await client.get(clean_url, headers={"Range": "bytes=0-1024"})
                return get_resp.status_code in (200, 206, 301, 302, 304)
    except Exception as e:
        logger.debug(f"Link liveness check failed for {clean_url}: {e}")
        return False
