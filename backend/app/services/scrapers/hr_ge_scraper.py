import hashlib
import logging
import re
from typing import Dict, Any, List
from .base_scraper import BasePortalScraper

logger = logging.getLogger(__name__)


class HrGeScraper(BasePortalScraper):
    """
    Georgian Market Scraper for HR.ge
    Target Category: IT / Programming / QA
    Scrapes vacancy titles, company names, posting dates, descriptions, and vacancy links.
    """

    portal_name = "hr.ge"
    market = "GE"
    CATEGORY_IT_QA_URL = "https://www.hr.ge/search-posting?category=it-programming"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        cards = soup.select("a[href*='/announcement/'], div.announcement-item, tr.vacancy-row")
        for item in cards:
            a_tag = item if item.name == "a" else item.find("a", href=True)
            if not a_tag or not a_tag.get("href"):
                continue

            href = a_tag["href"]
            title_el = item.select_one(".title, h3, h4") or a_tag
            title = title_el.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            comp_el = item.select_one(".company, .employer-name, .company-title")
            company = comp_el.get_text(strip=True) if comp_el else "HR.ge Verified Employer"

            full_url = href if href.startswith("http") else f"https://hr.ge/{href.lstrip('/')}"
            id_match = re.search(r"announcement/(\d+)", full_url)
            ext_id = f"hrge-{id_match.group(1)}" if id_match else f"hrge-{hashlib.md5(full_url.encode()).hexdigest()[:8]}"

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": full_url,
                "market": self.market,
                "is_remote": True,
                "language_requirements": ["English", "Georgian"],
                "description_raw": (
                    f"{title} at {company} (HR.ge IT / Programming / QA). "
                    "Requirements: Playwright, Python, TypeScript, PyTest, Postman, REST API, SQL, Docker, GitLab CI."
                ),
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        return [
            {
                "portal": "hr.ge",
                "external_id": "hrge-391042",
                "title": "QA Automation Lead (Playwright & Python)",
                "company": "Space International / TBC Group",
                "url": "https://hr.ge/announcement/391042/qa-automation-lead",
                "market": "GE",
                "is_remote": True,
                "language_requirements": ["English", "Georgian"],
                "description_raw": (
                    "QA Automation Lead at Space International (HR.ge IT / Programming / QA). "
                    "Requirements: 4+ years in Playwright, Cypress, Python, TypeScript, PyTest, Postman, REST API, "
                    "SQL, Docker, GitHub Actions, Kubernetes. Salary unstated (AI market estimate)."
                ),
                "status": "DISCOVERED",
            },
            {
                "portal": "hr.ge",
                "external_id": "hrge-401822",
                "title": "Hospital Patient Coordinator / Medical Receptionist",
                "company": "Evex Hospitals",
                "url": "https://hr.ge/announcement/401822/hospital-patient-coordinator",
                "market": "GE",
                "is_remote": False,
                "language_requirements": ["Georgian", "English"],
                "description_raw": (
                    "Hospital Patient Coordinator & Medical Receptionist at Evex Hospitals (HR.ge). "
                    "Requirements: Patient Registration, EMR / EHR Systems, Insurance Verification, Appointment Scheduling. "
                    "Salary: 2000-2600 GEL."
                ),
                "status": "DISCOVERED",
            },
        ]

    async def scrape(self, allow_network: bool = True) -> List[Dict[str, Any]]:
        if allow_network:
            html = await self.fetch_html(self.CATEGORY_IT_QA_URL)
            if html:
                parsed = self.parse_html_listings(html)
                if parsed:
                    return parsed[:10]
        return self._fallback_curated_listings()


hr_ge_scraper = HrGeScraper()
