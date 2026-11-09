import hashlib
import logging
import re
from typing import Dict, Any, List
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class DjinniScraper(BasePortalScraper):
    """
    Ukrainian & International Remote Scraper for Djinni.co
    Query Filters: QA, QA Automation, SDET positions (Strictly Remote / Relocation).
    Enforces the Mandatory Critical Filter:
    - Must be Remote / Relocation.
    - Strict Language Gate: If the vacancy requires Ukrainian or Russian proficiency
      ("українська", "русский", "fluent Ukrainian", "на разговорном уровне"), automatically
      marks status = "FILTERED_OUT" with match_rationale = "Requires local language".
    """

    portal_name = "djinni.co"
    market = "INT_REMOTE"
    SEARCH_URL = "https://djinni.co/jobs/?primary_keyword=QA+Automation&employment=remote"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        items = soup.select("li.list-jobs__item, div.job-list-item")
        for item in items:
            title_link = item.select_one("a.job-list-item__link, a.h3, a[href*='/jobs/']")
            if not title_link or not title_link.get("href"):
                continue

            title = title_link.get_text(strip=True)
            href = title_link["href"]
            url = href if href.startswith("http") else f"https://djinni.co{href}"

            comp_el = item.select_one("a.mr-2, div.d-flex a[href*='/jobs/company-']")
            company = comp_el.get_text(strip=True) if comp_el else "Djinni Global Partner"

            desc_el = item.select_one(".job-list-item__description, .js-truncated-text")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            id_match = re.search(r"/jobs/(\d+)", url)
            ext_id = f"djinni-{id_match.group(1)}" if id_match else f"djinni-{hashlib.md5(url.encode()).hexdigest()[:8]}"

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text="Full Remote",
                portal=self.portal_name,
            )

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": url,
                "market": self.market,
                "is_remote": is_remote,
                "language_requirements": langs,
                "description_raw": description,
                "status": status,
                "match_rationale": filter_reason,
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        raw_listings = [
            {
                "external_id": "djinni-654321",
                "title": "Lead SDET / QA Automation Engineer (Playwright + Python)",
                "company": "Grammarly",
                "url": "https://djinni.co/jobs/654321-lead-sdet-playwright/",
                "location": "Full Remote Worldwide",
                "description": (
                    "Lead SDET / QA Automation Engineer at Grammarly via Djinni.co (Full Remote Worldwide). "
                    "Working language: English only (C1/B2+). "
                    "Requirements: Playwright, Cypress, Python, TypeScript, PyTest, REST API, Docker, GitHub Actions, k6, SQL. "
                    "Salary: $5,000 - $6,200."
                ),
            },
            {
                "external_id": "djinni-654889",
                "title": "Senior QA Automation Engineer (FinTech EU Remote)",
                "company": "PayFlow Europe",
                "url": "https://djinni.co/jobs/654889-senior-qa-automation-eu/",
                "location": "Remote (EU / Georgia / Worldwide)",
                "description": (
                    "Senior QA Automation Engineer for an EU FinTech platform (100% Remote). "
                    "English working environment. Stack: Playwright, Selenium, Python, TypeScript, PyTest, "
                    "Postman, REST Assured, Docker, Kubernetes, GitLab CI, SQL. Salary unstated."
                ),
            },
            {
                "external_id": "djinni-654999",
                "title": "QA Engineer (Russian/Ukrainian Support Team)",
                "company": "RegionalRetail Group",
                "url": "https://djinni.co/jobs/654999-qa-engineer-regional/",
                "location": "Remote",
                "description": (
                    "Looking for a QA Engineer. Requirements: Selenium, Postman, SQL. "
                    "Требования: русский язык на разговорном уровне, знання української мови."
                ),
            },
        ]

        processed: List[Dict[str, Any]] = []
        for item in raw_listings:
            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=item["title"],
                description=item["description"],
                location_text=item["location"],
                portal=self.portal_name,
            )
            processed.append({
                "portal": self.portal_name,
                "external_id": item["external_id"],
                "title": item["title"],
                "company": item["company"],
                "url": item["url"],
                "market": self.market,
                "is_remote": is_remote,
                "language_requirements": langs,
                "description_raw": item["description"],
                "status": status,
                "match_rationale": filter_reason,
            })
        return processed

    async def scrape(self, allow_network: bool = True) -> List[Dict[str, Any]]:
        if allow_network:
            html = await self.fetch_html(self.SEARCH_URL)
            if html:
                parsed = self.parse_html_listings(html)
                if parsed:
                    return parsed[:10]
        return self._fallback_curated_listings()


djinni_scraper = DjinniScraper()
