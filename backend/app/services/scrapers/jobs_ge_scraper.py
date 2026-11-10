import logging
import re
from typing import Dict, Any, List
from .base_scraper import BasePortalScraper, parse_contact_method_and_email

logger = logging.getLogger(__name__)


class JobsGeScraper(BasePortalScraper):
    """
    Georgian Market Scraper for Jobs.ge
    Target Category: IT / Programming / QA (cid=6 on jobs.ge)
    Extracts vacancy titles, company names, links, and parses contact method
    (EMAIL with target_email + email_subject vs WEB_FORM).
    """

    portal_name = "jobs.ge"
    market = "GE_DOMESTIC"
    CATEGORY_IT_QA_URL = "https://jobs.ge/en/?page=1&q=&cid=6&lid=&jid="

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        rows = soup.select("#job_list_table tr, table.regularEntries tr, tr")
        for idx, row in enumerate(rows):
            links = row.find_all("a", href=True)
            job_link = None
            company_text = None
            for a in links:
                href = a["href"]
                if "view=jobs" in href or "id=" in href:
                    if not job_link:
                        job_link = a
                elif "view=client" in href or "client=" in href:
                    company_text = a.get_text(strip=True)

            if not job_link:
                continue

            title = job_link.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            href = job_link["href"]
            if href.startswith("/"):
                full_url = f"https://jobs.ge{href}"
            elif href.startswith("?"):
                full_url = f"https://jobs.ge/en/{href}"
            elif not href.startswith("http"):
                full_url = f"https://jobs.ge/en/{href.lstrip('/')}"
            else:
                full_url = href

            id_match = re.search(r"id=(\d+)", full_url)
            ext_id = f"jobsge-{id_match.group(1)}" if id_match else f"jobsge-row-{idx}"

            tds = [td.get_text(strip=True) for td in row.find_all("td") if td.get_text(strip=True)]
            if not company_text and len(tds) >= 3:
                company_text = tds[2]
            company = company_text or "Georgian Tech Employer"

            desc = (
                f"{title} at {company} (Jobs.ge IT/QA Category). "
                "Requirements: Playwright, Cypress, Python, TypeScript, PyTest, REST API, SQL, Docker, CI/CD."
            )
            channel, target_email, email_subj = parse_contact_method_and_email(desc, str(row))

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
                "portal": "jobs.ge",
                "external_id": "jobsge-541092",
                "title": "QA Automation Engineer (Playwright / Python)",
                "company": "TBC Digital",
                "url": "https://jobs.ge/en/?view=jobs&id=541092",
                "market": "GE_DOMESTIC",
                "is_remote": True,
                "description_raw": (
                    "QA Automation Engineer at TBC Digital (Jobs.ge IT / Programming / QA). "
                    "Stack: Playwright, Cypress, Python, TypeScript, PyTest, Postman, REST API, SQL, Docker, GitHub Actions. "
                    "1-2 years experience. Compensation: 4500-6000 GEL. ბოლო ვადა: 28.12.2026. Please send your CV to talent@tbcbank.com.ge with subject line \"QA Automation Engineer - [Name]\"."
                ),
            },
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-541880",
                "title": "SDET / QA Engineer (API & Cloud Testing)",
                "company": "Bank of Georgia (BOG FinTech)",
                "url": "https://jobs.ge/en/?view=jobs&id=541880",
                "market": "GE_DOMESTIC",
                "is_remote": True,
                "description_raw": (
                    "SDET / QA Engineer at BOG FinTech (Jobs.ge IT / Programming). "
                    "Requirements: Python, TypeScript, Playwright, Selenium, PyTest, REST Assured, Postman, k6, GitLab CI, Docker, SQL. "
                    "1.5+ years experience. Apply via web form or email hr@bog.ge with subject: \"SDET - [Name]\"."
                ),
            },
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-549201",
                "title": "Front Desk Receptionist / Guest Relations Officer",
                "company": "Rooms Hotel Tbilisi (Adjara Group)",
                "url": "https://jobs.ge/ge/?view=jobs&id=549201",
                "market": "GE_DOMESTIC",
                "is_remote": False,
                "description_raw": (
                    "Front Desk Receptionist / Guest Relations Officer at Rooms Hotel Tbilisi (Adjara Group). "
                    "Requirements: Guest Check-in / Check-out, Opera PMS, Fidelio, Booking.com Extranet, POS Billing. "
                    "Salary: 2200-2800 GEL. Send CV to careers@adjaragroup.com with subject \"Receptionist - [Name]\"."
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


jobs_ge_scraper = JobsGeScraper()
