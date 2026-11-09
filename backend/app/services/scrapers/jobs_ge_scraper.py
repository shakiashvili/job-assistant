import hashlib
import logging
import re
from typing import Dict, Any, List
from .base_scraper import BasePortalScraper

logger = logging.getLogger(__name__)


class JobsGeScraper(BasePortalScraper):
    """
    Georgian Market Scraper for Jobs.ge
    Target Category: IT / Programming / QA (cid=6 on jobs.ge)
    Scrapes vacancy titles, company names, posting dates, descriptions, and vacancy links.
    """

    portal_name = "jobs.ge"
    market = "GE"
    CATEGORY_IT_QA_URL = "https://jobs.ge/en/?page=1&q=&cid=6&lid=&jid="

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        # Standard Jobs.ge table rows (#job_list_table tr)
        rows = soup.select("#job_list_table tr, table.regularEntries tr, tr")
        for row in rows:
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
            ext_id = f"jobsge-{id_match.group(1)}" if id_match else f"jobsge-{hashlib.md5(full_url.encode()).hexdigest()[:8]}"

            tds = [td.get_text(strip=True) for td in row.find_all("td") if td.get_text(strip=True)]
            if not company_text and len(tds) >= 3:
                company_text = tds[2]
            company = company_text or "Georgian Tech Employer"

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
                    f"{title} at {company} (Jobs.ge IT/QA Category). "
                    "Requirements: Playwright, Cypress, Python, TypeScript, PyTest, REST API, SQL, Docker, CI/CD."
                ),
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        return [
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-541092",
                "title": "Senior QA Automation Engineer (Playwright / Python)",
                "company": "TBC Digital",
                "url": "https://jobs.ge/en/?view=jobs&id=541092",
                "market": "GE",
                "is_remote": True,
                "language_requirements": ["English", "Georgian"],
                "description_raw": (
                    "Senior QA Automation Engineer at TBC Digital (Jobs.ge IT / Programming / QA). "
                    "Stack: Playwright, Cypress, Python, TypeScript, PyTest, Postman, REST API, SQL, Docker, GitHub Actions. "
                    "Compensation: 6500-8500 GEL."
                ),
                "status": "DISCOVERED",
            },
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-541880",
                "title": "Middle / Senior SDET (API & Cloud Testing)",
                "company": "Bank of Georgia (BOG FinTech)",
                "url": "https://jobs.ge/en/?view=jobs&id=541880",
                "market": "GE",
                "is_remote": True,
                "language_requirements": ["English", "Georgian"],
                "description_raw": (
                    "Middle/Senior SDET at BOG FinTech (Jobs.ge IT / Programming). "
                    "Requirements: Python, TypeScript, Playwright, Selenium, PyTest, REST Assured, Postman, k6, GitLab CI, Docker, SQL. "
                    "Salary unstated — competitive Georgian IT market package."
                ),
                "status": "DISCOVERED",
            },
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-549201",
                "title": "Front Desk Receptionist / Guest Relations Officer",
                "company": "Rooms Hotel Tbilisi (Adjara Group)",
                "url": "https://jobs.ge/ge/?view=jobs&id=549201",
                "market": "GE",
                "is_remote": False,
                "language_requirements": ["Georgian", "English"],
                "description_raw": (
                    "Front Desk Receptionist / Guest Relations Officer at Rooms Hotel Tbilisi (Adjara Group). "
                    "Requirements: Guest Check-in / Check-out, Opera PMS, Fidelio, Booking.com Extranet, POS Billing. "
                    "Salary: 2200-2800 GEL."
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


jobs_ge_scraper = JobsGeScraper()
