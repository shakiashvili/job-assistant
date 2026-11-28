import re
from typing import Tuple, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup

HOSTNAME_PORTAL_MAP = {
    "jobs.dou.ua": "dou.ua",
    "dou.ua": "dou.ua",
    "djinni.co": "djinni.co",
    "jobs.ge": "jobs.ge",
    "www.jobs.ge": "jobs.ge",
    "hr.ge": "hr.ge",
    "www.hr.ge": "hr.ge",
    "headhunter.ge": "headhunter.ge",
    "hh.ge": "headhunter.ge",
    "justjoin.it": "justjoin.it",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "lever.co": "lever",
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
}


KNOWN_PORTALS = set(HOSTNAME_PORTAL_MAP.values())


def _extract_http_hostname(url: str) -> Optional[str]:
    """Extracts normalized hostname only for HTTP/HTTPS (or scheme-less web) URLs."""
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(("file:", "javascript:", "data:", "mailto:", "about:")):
        return None

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None

    return parsed.hostname.lower().strip().rstrip(".")


def detect_portal_from_url(url: str) -> str:
    """
    Detects portal strictly using canonical URL hostname parsing (urllib.parse.urlparse).
    """
    hostname = _extract_http_hostname(url)
    if not hostname:
        return "custom"

    if hostname in HOSTNAME_PORTAL_MAP:
        return HOSTNAME_PORTAL_MAP[hostname]

    for domain, portal in HOSTNAME_PORTAL_MAP.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return portal

    return "custom"


def detect_portal_from_html(html: str, url: Optional[str] = None) -> Tuple[str, dict]:
    """
    Extracts job metadata from HTML using semantic DOM selectors and canonical URL hostname parsing.
    When an HTTP/HTTPS URL is provided, its hostname is authoritative and HTML metadata/links
    cannot spoof another portal. HTML structural markers are inspected only for local/URL-less inputs.
    """
    hostname = _extract_http_hostname(url or "")
    portal_type = detect_portal_from_url(url or "")
    soup = BeautifulSoup(html or "", "html.parser")

    if portal_type == "custom" and hostname is None:
        board_el = soup.find(True, attrs={"data-board": True})
        board_val = str(board_el.get("data-board", "")).strip().lower() if board_el else ""
        if board_val in KNOWN_PORTALS:
            portal_type = board_val
        elif soup.find("input", attrs={"name": re.compile(r"^job_application\[", re.I)}):
            portal_type = "greenhouse"
        elif soup.find("input", attrs={"name": "urls[LinkedIn]"}):
            portal_type = "lever"
        elif soup.find("form", id="dou-apply-form"):
            portal_type = "dou.ua"
        elif soup.find("form", id="djinni-apply-form"):
            portal_type = "djinni.co"
        elif soup.find("form", id="jobsge-apply-form"):
            portal_type = "jobs.ge"
        elif soup.find("form", id="justjoin-apply-form"):
            portal_type = "justjoin.it"

    # Extract Title via semantic headings / OpenGraph metadata
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1_el = soup.find("h1")
    if h1_el and h1_el.get_text(strip=True):
        title = h1_el.get_text(strip=True)
    elif og_title and og_title.get("content"):
        title = str(og_title["content"]).strip()

    # Extract Company via semantic selectors
    company = ""
    company_el = (
        soup.find(True, attrs={"itemprop": "hiringOrganization"})
        or soup.find("a", class_=re.compile(r"company", re.I))
        or soup.find("div", class_=re.compile(r"company|employer|posting-headline", re.I))
        or soup.find("span", class_=re.compile(r"company", re.I))
    )
    if company_el:
        company = company_el.get_text(strip=True).split("•")[0].strip()

    # Extract substantive description text
    main_el = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"description|vacancy|job-details|posting|b-typo|content", re.I))
        or soup.body
        or soup
    )
    desc_text = main_el.get_text(separator="\n", strip=True) if main_el else ""

    return portal_type, {
        "title": title,
        "company": company,
        "description_text": desc_text[:15000],
    }
