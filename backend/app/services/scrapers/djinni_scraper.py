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

    def parse_html_listings(
        self,
        html: str,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
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

            comp_el = item.select_one("a[href*='/jobs/company-'], span.font-weight-500, a.mr-2")
            company = comp_el.get_text(" ", strip=True) if comp_el else "Djinni Global Employer"

            # Extract ONLY clean role title without concatenated company, fire emojis, "Responds Quickly", or "to $700"
            inner_pos = title_link.select_one("h2.job-item__position, .job-item__position, .h3")
            if inner_pos:
                title = inner_pos.get_text(" ", strip=True)
            else:
                direct_txt = "".join(
                    t for t in title_link.find_all(string=True, recursive=False)
                ).strip()
                title = direct_txt or title_link.get_text(" ", strip=True)

            # Strip accidental badge/salary/company suffixes if Djinni card nested them into header-link
            title = re.sub(r"🔥+", "", title)
            title = re.sub(r"\bResponds Quickly\b.*$", "", title, flags=re.IGNORECASE)
            title = re.sub(
                r"\s+(?:up\s+to|to|from)\s+[\$€£]\s*\d[\d,]*(?:\s*[–\-]\s*[\$€£]?\s*\d[\d,]*)?.*$",
                "",
                title,
                flags=re.IGNORECASE,
            )
            title = re.sub(r"\s+\$+\s*$", "", title)
            if company and company != "Djinni Global Employer" and len(company) > 2:
                comp_idx = title.find(f" {company}")
                if comp_idx > 4:
                    title = title[:comp_idx]
            title = re.sub(r"\s+", " ", title).strip()
            if not title or len(title) < 3 or re.fullmatch(r"[\$€£\s]+", title):
                continue

            # Extract explicit card salary badge ("to $700", "$1500 - $2500") while ignoring bare "$"
            sal_parts: List[str] = []
            for badge in item.select("span, div.col-auto, strong, a.job_item__header-link"):
                bt = badge.get_text(" ", strip=True)
                for m in re.finditer(
                    r"(?:(?:up\s+to|to|from)\s+)?[\$€£]\s*\d{3,}(?:\s*[–\-]\s*[\$€£]?\s*\d{3,})?",
                    bt,
                    flags=re.IGNORECASE,
                ):
                    sal_parts.append(m.group(0).strip())
            card_salary = " | ".join(dict.fromkeys(sal_parts))

            url = href if href.startswith("http") else f"https://djinni.co{href}"

            id_match = re.search(r"/jobs/(\d+)", url)
            ext_id = f"djinni-{id_match.group(1)}" if id_match else f"djinni-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            meta_el = item.select_one("div.fw-medium")
            meta_text = meta_el.get_text(" ", strip=True) if meta_el else "Full Remote"

            desc_el = item.select_one(
                "span.js-original-text, span.js-truncated-text, .job-list-item__description"
            )
            desc_body = desc_el.get_text(" ", strip=True) if desc_el else title
            description_parts = [p for p in [card_salary, meta_text, desc_body] if p]
            description = " | ".join(description_parts)

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc_body,
                location_text=meta_text,
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

    async def _enrich_and_verify_item(
        self,
        item: Dict[str, Any],
        candidate_languages: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
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
        # Preserve any card salary extracted from list view (e.g. "to $700")
        prev_head = (item.get("description_raw") or "").split("|")[0].strip()
        if not sal_txt and re.search(r"[\$€£]\s*\d{3,}", prev_head):
            sal_txt = prev_head
        loc_meta = item.get("location_meta") or "Full Remote"
        full_desc = f"{loc_meta} | {sal_txt} | {full_body}".strip(" |")

        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=full_body,
            location_text=loc_meta,
            portal=self.portal_name,
            candidate_languages=candidate_languages,
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
        candidate_languages: Optional[List[str]] = None,
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
                for item in self.parse_html_listings(html, candidate_languages=candidate_languages):
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
                *(self._enrich_and_verify_item(c, candidate_languages=candidate_languages) for c in non_filtered),
                return_exceptions=True,
            )
            verified_non_filtered = [x for x in enriched if isinstance(x, dict)]
        else:
            verified_non_filtered = []

        return verified_non_filtered + filtered_stub


djinni_scraper = DjinniScraper()
