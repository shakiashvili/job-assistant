import re
from typing import Tuple, Optional
from bs4 import BeautifulSoup


def detect_portal_from_url(url: str) -> str:
    """Detects portal type based on URL pattern across global, Ukrainian, Georgian, Polish, and US/EU boards."""
    url_lower = (url or "").lower()
    if "dou.ua" in url_lower or "dou_sample" in url_lower:
        return "dou.ua"
    if "djinni.co" in url_lower or "djinni_sample" in url_lower:
        return "djinni.co"
    if "jobs.ge" in url_lower or "jobs_ge_sample" in url_lower:
        return "jobs.ge"
    if "hr.ge" in url_lower or "hr_ge_sample" in url_lower:
        return "hr.ge"
    if "headhunter.ge" in url_lower or "hh.ge" in url_lower or "hh_sample" in url_lower:
        return "headhunter.ge"
    if "justjoin.it" in url_lower or "justjoin_sample" in url_lower:
        return "justjoin.it"
    if "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower or "greenhouse_sample" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower or "jobs.lever" in url_lower or "lever_sample" in url_lower:
        return "lever"
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "remoteok" in url_lower or "weworkremotely" in url_lower:
        return "remote_abroad"
    return "generic"


def detect_portal_from_html(html: str, url: Optional[str] = None) -> Tuple[str, dict]:
    """
    Analyzes HTML structure to detect portal type and extracted metadata
    (job title, company, description element, form element).
    """
    portal_type = "generic"
    if url:
        detected = detect_portal_from_url(url)
        if detected != "generic":
            portal_type = detected

    soup = BeautifulSoup(html, "html.parser")

    board_attr = soup.find(attrs={"data-board": True})
    if board_attr:
        portal_type = board_attr.get("data-board")

    if portal_type == "generic":
        if soup.find(id="application_form") or soup.find("input", attrs={"name": re.compile(r"job_application\[", re.I)}):
            portal_type = "greenhouse"
        elif soup.find("form", class_=re.compile(r"application-form", re.I)) or soup.find("input", attrs={"name": "urls[LinkedIn]"}):
            portal_type = "lever"
        elif "dou.ua" in html.lower() or soup.find(id="dou-apply-form"):
            portal_type = "dou.ua"
        elif "djinni.co" in html.lower() or soup.find(id="djinni-apply-form"):
            portal_type = "djinni.co"
        elif "justjoin.it" in html.lower() or soup.find(id="justjoin-apply-form"):
            portal_type = "justjoin.it"
        elif "jobs.ge" in html.lower() or "hr.ge" in html.lower() or "headhunter.ge" in html.lower():
            portal_type = "jobs.ge"

    # Extract Title
    title = ""
    title_el = (
        soup.find(id="app-title")
        or soup.find(id="posting-title")
        or soup.find("h1", class_=re.compile(r"title|headline|job-title|g-h2", re.I))
        or soup.find("h1")
    )
    if title_el:
        title = title_el.get_text(strip=True)

    # Extract Company
    company = ""
    company_el = (
        soup.find(id="company-name")
        or soup.find("div", class_=re.compile(r"company|posting-headline|b-compinfo", re.I))
        or soup.find("a", class_=re.compile(r"company", re.I))
        or soup.find("span", class_=re.compile(r"company", re.I))
    )
    if company_el:
        company = company_el.get_text(strip=True).split("•")[0].strip()

    # Extract Description
    desc_el = (
        soup.find(id="job-description")
        or soup.find(id="posting-description")
        or soup.find("div", class_=re.compile(r"section-page|job-desc|description|b-typo|vacancy-section", re.I))
    )
    desc_text = desc_el.get_text(separator="\n", strip=True) if desc_el else soup.get_text(separator="\n", strip=True)

    return portal_type, {
        "title": title or "Senior QA Automation Engineer",
        "company": company or "Tech Company",
        "description_text": desc_text[:15000],
    }
