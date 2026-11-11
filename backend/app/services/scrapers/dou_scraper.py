import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class DouScraper(BasePortalScraper):
    """
    Ukrainian & Regional Portal Scraper for DOU.ua (jobs.dou.ua).
    Fetches full detail pages so Ukrainian city/UI metadata does not trigger
    false language rejections on English-language Global Remote openings, while
    still strictly filtering out roles whose requirements demand Ukrainian/Russian.
    """

    portal_name = "dou.ua"
    market = "UA_REMOTE"
    SEARCH_URL = "https://jobs.dou.ua/vacancies/?category=QA&remote"

    def parse_html_listings(
        self,
        html: str,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

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
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=description,
                location_text=location_text,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": url,
                "market": self.market,
                "is_remote": is_remote,
                "location_meta": location_text,
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

    async def _enrich_and_verify_item(
        self,
        item: Dict[str, Any],
        candidate_languages: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetches full DOU vacancy body so English/language requirements evaluate accurately."""
        html = await self.fetch_html(item["url"], timeout=8.0)
        if not html:
            return item

        soup = self.make_soup(html)
        desc_el = soup.select_one("div.b-typo.vacancy-section, div.l-vacancy")
        if not desc_el:
            return item

        body_text = desc_el.get_text(" ", strip=True)
        sal_el = soup.select_one("span.salary")
        sal_txt = sal_el.get_text(" ", strip=True) if sal_el else ""
        loc_meta = item.get("location_meta") or "Remote"

        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=body_text,
            location_text=loc_meta,
            portal=self.portal_name,
            candidate_languages=candidate_languages,
        )
        full_desc = f"{sal_txt} | {body_text}".strip(" |") if sal_txt else body_text
        item["is_remote"] = is_remote
        item["status"] = status
        item["filter_out_reason"] = filter_reason or None
        item["match_rationale"] = filter_reason
        item["detected_languages"] = langs
        item["language_requirements"] = langs
        item["description_raw"] = full_desc[:6000]
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        search_url: Optional[str] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_url = search_url or self.SEARCH_URL
        urls = [target_url]
        if "category=QA" in target_url and "search=" not in target_url:
            urls.append("https://jobs.dou.ua/vacancies/?category=QA&search=Automation&remote")

        pages = await asyncio.gather(*(self.fetch_html(u) for u in urls), return_exceptions=True)
        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(html, candidate_languages=candidate_languages):
                    if item["external_id"] not in seen_ids:
                        seen_ids.add(item["external_id"])
                        candidates.append(item)

        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c, candidate_languages=candidate_languages) for c in candidates[:18]),
            return_exceptions=True,
        )
        return [x for x in enriched if isinstance(x, dict)]


dou_scraper = DouScraper()
