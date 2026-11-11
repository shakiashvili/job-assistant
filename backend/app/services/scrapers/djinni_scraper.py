import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class DjinniScraper(BasePortalScraper):
    """
    Live Remote Scraper for Djinni.co.
    Searches multiple pages & role queries dynamically (e.g., QA + QA Automation),
    fetches detail pages for full technical requirements, and strictly filters
    against Ukrainian/Russian requirements and non-remote / Ukraine-only restrictions.
    """

    portal_name = "djinni.co"
    market = "GLOBAL_REMOTE"
    SEARCH_URL = "https://djinni.co/jobs/?primary_keyword=QA&employment=remote"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

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

            # Extract clean job title from the anchor text (NOT h2 wrapper which includes company/$ badges)
            title = title_link.get_text(" ", strip=True)
            title = re.sub(r"\s+\$+\s*$", "", title).strip()
            if not title or len(title) < 3:
                continue

            url = href if href.startswith("http") else f"https://djinni.co{href}"

            id_match = re.search(r"/jobs/(\d+)", url)
            ext_id = f"djinni-{id_match.group(1)}" if id_match else f"djinni-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            comp_el = item.select_one("a[href*='/jobs/company-'], span.font-weight-500, a.mr-2")
            company = comp_el.get_text(" ", strip=True) if comp_el else "Djinni Global Employer"

            meta_el = item.select_one("div.fw-medium")
            meta_text = meta_el.get_text(" ", strip=True) if meta_el else "Full Remote"

            desc_el = item.select_one(
                "span.js-original-text, span.js-truncated-text, .job-list-item__description"
            )
            desc_body = desc_el.get_text(" ", strip=True) if desc_el else title
            description = f"{meta_text} | {desc_body}" if meta_text else desc_body

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc_body,
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
                "location_meta": meta_text,
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

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetches the live Djinni detail page for deep skill/language/salary/location inspection."""
        html = await self.fetch_html(item["url"], timeout=8.0)
        if not html:
            return item

        soup = self.make_soup(html)
        desc_el = soup.select_one("div.job-post__description, main, article")
        full_body = desc_el.get_text(" ", strip=True) if desc_el else ""
        if len(full_body) < 80:
            return item

        sal_el = soup.select_one("span.public-salary-item")
        sal_txt = sal_el.get_text(" ", strip=True) if sal_el else ""
        loc_meta = item.get("location_meta") or "Full Remote"
        full_desc = f"{loc_meta} | {sal_txt} | {full_body}".strip(" |")

        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=full_body,
            location_text=loc_meta,
            portal=self.portal_name,
        )
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
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        base_url = search_url or self.SEARCH_URL
        urls = [base_url, f"{base_url}&page=2"]
        if "primary_keyword=QA&" in base_url:
            urls.append(base_url.replace("primary_keyword=QA", "primary_keyword=QA+Automation"))

        pages = await asyncio.gather(*(self.fetch_html(u) for u in urls), return_exceptions=True)

        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(html):
                    if item["external_id"] not in seen_ids:
                        seen_ids.add(item["external_id"])
                        candidates.append(item)

        if not candidates:
            return []

        # Keep already non-filtered candidates first for deep detail page enrichment (top 22)
        non_filtered = [c for c in candidates if c.get("status") != "FILTERED_OUT"][:22]
        filtered_stub = [c for c in candidates if c.get("status") == "FILTERED_OUT"]

        if non_filtered:
            enriched = await asyncio.gather(
                *(self._enrich_and_verify_item(c) for c in non_filtered),
                return_exceptions=True,
            )
            verified_non_filtered = [x for x in enriched if isinstance(x, dict)]
        else:
            verified_non_filtered = []

        return verified_non_filtered + filtered_stub


djinni_scraper = DjinniScraper()
