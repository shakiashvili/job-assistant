import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class DouScraper(BasePortalScraper):
    """
    Ukrainian & Regional Portal Scraper for DOU.ua (jobs.dou.ua)
    Query Filters: QA, QA Automation, SDET positions (Remote / Relocation).
    Enforces Strict Remote Gate & Strict Slavic Language Filter:
    - Any vacancy requiring Ukrainian or Russian fluency (вільно, українськ, русский, разговорный)
      is marked status = "FILTERED_OUT" with filter_out_reason = "Mandatory local Slavic language requirement".
    """

    portal_name = "dou.ua"
    market = "UA_REMOTE"
    SEARCH_URL = "https://jobs.dou.ua/vacancies/?category=QA&remote"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []

        items = soup.select("li.l-vacancy, div.vacancy")
        for idx, item in enumerate(items):
            title_link = item.select_one("a.vt, div.title a")
            if not title_link or not title_link.get("href"):
                continue

            title = title_link.get_text(strip=True)
            url = title_link["href"]
            comp_el = item.select_one("a.company, strong a")
            company = comp_el.get_text(strip=True) if comp_el else "DOU Tech Employer"
            city_el = item.select_one("span.cities")
            location_text = city_el.get_text(strip=True) if city_el else "Remote"
            desc_el = item.select_one("div.sh-info")
            description = desc_el.get_text(" ", strip=True) if desc_el else title

            id_match = re.search(r"vacancies/(\d+)", url)
            ext_id = f"dou-{id_match.group(1)}" if id_match else f"dou-row-{idx}"

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text=location_text,
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
                "channel": "WEB_FORM",
                "detected_languages": langs,
                "language_requirements": langs,
                "description_raw": description,
                "status": status,
                "filter_out_reason": filter_reason or None,
                "match_rationale": filter_reason,
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        """Purged: never inject dead static vacancies when offline."""
        return []

    async def scrape(
        self,
        allow_network: bool = True,
        search_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_url = search_url or self.SEARCH_URL
        html = await self.fetch_html(target_url)
        if html:
            parsed = self.parse_html_listings(html)
            if parsed:
                return parsed[:10]
        return []


dou_scraper = DouScraper()
