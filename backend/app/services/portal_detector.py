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


def detect_portal_from_url(url: str) -> str:
    """
    Detects portal strictly using canonical URL hostname parsing (urllib.parse.urlparse).
    """
    if not url:
        return "custom"

    parsed = urlparse(url if "://" in url else f"https://{url}")
    hostname = (parsed.hostname or "").lower().strip()

    if hostname in HOSTNAME_PORTAL_MAP:
        return HOSTNAME_PORTAL_MAP[hostname]

    for domain, portal in HOSTNAME_PORTAL_MAP.items():
        if hostname.endswith(f".{domain}") or hostname == domain:
            return portal

    return "custom"


def detect_portal_from_html(html: str, url: Optional[str] = None) -> Tuple[str, dict]:
    """
    Extracts job metadata from HTML using semantic DOM selectors and canonical URL hostname parsing.
    """
    portal_type = detect_portal_from_url(url or "")
    soup = BeautifulSoup(html or "", "html.parser")

    if portal_type == "custom":
        doc_title = (soup.title.string if soup.title and soup.title.string else "").lower()
        canonical_link = soup.find("link", rel="canonical")
        if canonical_link and canonical_link.get("href"):
            portal_type = detect_portal_from_url(str(canonical_link["href"]))

        if portal_type == "custom":
            if (
                "greenhouse" in doc_title
                or soup.find("meta", attrs={"property": "og:site_name", "content": re.compile(r"Greenhouse", re.I)})
                or soup.find("input", attrs={"name": re.compile(r"job_application\[", re.I)})
                or soup.find(id="first_name")
            ):
                portal_type = "greenhouse"
            elif (
                "lever" in doc_title
                or soup.find("form", class_=re.compile(r"application-form", re.I))
                or soup.find("input", attrs={"name": "urls[LinkedIn]"})
            ):
                portal_type = "lever"
            elif "dou.ua" in doc_title or soup.find("a", href=re.compile(r"dou\.ua", re.I)):
                portal_type = "dou.ua"
            elif "djinni" in doc_title or soup.find("a", href=re.compile(r"djinni\.co", re.I)):
                portal_type = "djinni.co"
            elif "jobs.ge" in doc_title or soup.find("a", href=re.compile(r"jobs\.ge", re.I)):
                portal_type = "jobs.ge"
            elif "hr.ge" in doc_title or soup.find("a", href=re.compile(r"hr\.ge", re.I)):
                portal_type = "hr.ge"

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
        soup.find(attrs={"itemprop": "hiringOrganization"})
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
        "title": title or "Senior QA Automation Engineer",
        "company": company or "Tech Company",
        "description_text": desc_text[:15000],
    }
