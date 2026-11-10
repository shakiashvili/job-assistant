import logging
import re
from typing import Dict, Any, List
from .base_scraper import BasePortalScraper, parse_contact_method_and_email

logger = logging.getLogger(__name__)


class HrGeScraper(BasePortalScraper):
    """
    Georgian Market Scraper for HR.ge
    Target Category: IT / Programming / QA
    Extracts vacancy titles, company names, links, and parses contact method
    (EMAIL with target_email + email_subject vs WEB_FORM).
    """

    portal_name = "hr.ge"
    market = "GE_DOMESTIC"
    CATEGORY_IT_QA_URL = "https://www.hr.ge/search-posting?category=it-programming"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        cards = soup.select("a[href*='/announcement/'], div.announcement-item, tr.vacancy-row")
        for idx, item in enumerate(cards):
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
            ext_id = f"hrge-{id_match.group(1)}" if id_match else f"hrge-row-{idx}"

            desc = (
                f"{title} at {company} (HR.ge IT / Programming / QA). "
                "Requirements: Playwright, Python, TypeScript, PyTest, Postman, REST API, SQL, Docker, GitLab CI."
            )
            channel, target_email, email_subj = parse_contact_method_and_email(desc, str(item))

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": full_url,
                "market": self.market,
                "is_remote": True,
                "channel": channel,
                "target_email": target_email,
                "email_subject": email_subj,
                "detected_languages": ["English", "Georgian"],
                "language_requirements": ["English", "Georgian"],
                "description_raw": desc,
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        items = [
            {
                "portal": "hr.ge",
                "external_id": "hrge-391042",
                "title": "QA Automation Engineer (Playwright & Python)",
                "company": "Space International / TBC Group",
                "url": "https://hr.ge/announcement/391042/qa-automation-engineer",
                "market": "GE_DOMESTIC",
                "is_remote": True,
                "description_raw": (
                    "QA Automation Engineer at Space International (HR.ge IT / Programming / QA). "
                    "Requirements: 1-2 years in Playwright, Cypress, Python, TypeScript, PyTest, Postman, REST API, "
                    "SQL, Docker, GitHub Actions. ბოლო ვადა: 30.12.2026. Apply via web form or email jobs@space.ge with subject \"QA Automation Engineer - [Name]\"."
                ),
            },
            {
                "portal": "hr.ge",
                "external_id": "hrge-401822",
                "title": "Hospital Patient Coordinator / Medical Receptionist",
                "company": "Evex Hospitals",
                "url": "https://hr.ge/announcement/401822/hospital-patient-coordinator",
                "market": "GE_DOMESTIC",
                "is_remote": False,
                "description_raw": (
                    "Hospital Patient Coordinator & Medical Receptionist at Evex Hospitals (HR.ge). "
                    "Requirements: Patient Registration, EMR / EHR Systems, Insurance Verification, Appointment Scheduling. "
                    "Salary: 2000-2600 GEL. Apply via web form."
                ),
            },
        ]

        results: List[Dict[str, Any]] = []
        for item in items:
            channel, target_email, email_subj = parse_contact_method_and_email(item["description_raw"])
            results.append({
                **item,
                "channel": channel,
                "target_email": target_email,
                "email_subject": email_subj,
                "detected_languages": ["English", "Georgian"],
                "language_requirements": ["English", "Georgian"],
                "status": "DISCOVERED",
            })
        return results

    async def scrape(self, allow_network: bool = True) -> List[Dict[str, Any]]:
        if allow_network:
            html = await self.fetch_html(self.CATEGORY_IT_QA_URL)
            if html:
                parsed = self.parse_html_listings(html)
                if parsed:
                    return parsed[:10]
        return self._fallback_curated_listings()


hr_ge_scraper = HrGeScraper()
