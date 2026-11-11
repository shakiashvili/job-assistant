import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class DjinniScraper(BasePortalScraper):
    """
    Live Remote Scraper for Djinni.co.
    Search URL dynamically driven by candidate role (e.g., primary_keyword=QA&employment=remote).
    Enforces Strict Remote Gate & Strict Slavic Language Filter:
    - Any vacancy requiring Ukrainian or Russian fluency is marked FILTERED_OUT.
    """

    portal_name = "djinni.co"
    market = "GLOBAL_REMOTE"
    SEARCH_URL = "https://djinni.co/jobs/?primary_keyword=QA&employment=remote"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Live Djinni DOM uses div.job-item (legacy fallback li.list-jobs__item / div.job-list-item)
        items = soup.select("div.job-item, li[id^='job-item-'], li.list-jobs__item, div.job-list-item")
        for idx, item in enumerate(items):
            title_link = item.select_one(
                "a.job_item__header-link, a.job-list-item__link, a.h3, a[href*='/jobs/']"
            )
            if not title_link or not title_link.get("href"):
                continue

            href = title_link["href"]
            if "/jobs/" not in href or "primary_keyword=" in href:
                continue

            # Extract title from h2.job-item__position if present
            title_el = item.select_one("h2.job-item__position") or title_link
            title = title_el.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue

            url = href if href.startswith("http") else f"https://djinni.co{href}"

            id_match = re.search(r"/jobs/(\d+)", url)
            ext_id = f"djinni-{id_match.group(1)}" if id_match else f"djinni-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            comp_el = item.select_one("span.font-weight-500, a[href*='/jobs/company-'], a.mr-2")
            company = comp_el.get_text(" ", strip=True) if comp_el else "Djinni Global Partner"

            meta_el = item.select_one("div.fw-medium")
            meta_text = meta_el.get_text(" ", strip=True) if meta_el else "Full Remote"

            # Prefer full untruncated description text when available
            desc_el = item.select_one(
                "span.js-original-text, span.js-truncated-text, .job-list-item__description"
            )
            desc_body = desc_el.get_text(" ", strip=True) if desc_el else title
            description = f"{meta_text} | {desc_body}" if meta_text else desc_body

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text=meta_text,
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
                "description_raw": description[:4000],
                "status": status,
                "filter_out_reason": filter_reason or None,
                "match_rationale": filter_reason,
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        """Purged: never return fake static listings when offline."""
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
                return parsed[:15]
        return []


djinni_scraper = DjinniScraper()
