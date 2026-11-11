import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, parse_contact_method_and_email
from ..link_validator import fetch_and_validate_live_vacancy

logger = logging.getLogger(__name__)


class HrGeScraper(BasePortalScraper):
    """
    Live Georgian Market Scraper for HR.ge.
    Extracts matching announcements by target role keywords and verifies every detail URL live.
    """

    portal_name = "hr.ge"
    market = "GE_DOMESTIC"
    CATEGORY_IT_QA_URL = "https://www.hr.ge/search-posting?q=QA"

    def parse_html_listings(
        self,
        html: str,
        domain_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        kw_list = [k.lower() for k in (domain_keywords or ["qa", "quality assurance", "tester", "test", "sdet", "ტესტ"])]

        cards = soup.select("a[href*='/announcement/'], div.announcement-item, tr.vacancy-row")
        for idx, item in enumerate(cards):
            a_tag = item if item.name == "a" else item.find("a", href=True)
            if not a_tag or not a_tag.get("href"):
                continue

            href = a_tag["href"]
            if "favorites" in href:
                continue

            title_el = item.select_one(".title, h3, h4") or a_tag
            title = title_el.get_text(" ", strip=True)
            if not title or len(title) < 4:
                continue

            # Filter out SSR sidebar/unrelated tiles immediately by domain keywords
            lower_title = title.lower()
            if not any(kw in lower_title for kw in kw_list):
                continue

            comp_el = item.select_one(".company, .employer-name, .company-title")
            company = comp_el.get_text(" ", strip=True) if comp_el else "HR.ge Verified Employer"

            full_url = href if href.startswith("http") else f"https://www.hr.ge/{href.lstrip('/')}"
            id_match = re.search(r"announcement/(\d+)", full_url)
            ext_id = f"hrge-{id_match.group(1)}" if id_match else f"hrge-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            prelim_desc = f"{title} at {company} (HR.ge)"
            channel, target_email, email_subj = parse_contact_method_and_email(prelim_desc, str(item))

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": full_url,
                "market": self.market,
                "is_remote": False,
                "channel": channel,
                "target_email": target_email,
                "email_subject": email_subj,
                "detected_languages": ["English", "Georgian"],
                "language_requirements": ["English", "Georgian"],
                "description_raw": prelim_desc,
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        """Purged: never inject dead static vacancies when offline."""
        return []

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        is_live, clean_text, raw_html = await fetch_and_validate_live_vacancy(item["url"], timeout=8.0)
        if not is_live or not clean_text:
            return None

        item["description_raw"] = clean_text
        item["is_link_live"] = True
        lower_desc = clean_text.lower()
        item["is_remote"] = any(
            w in lower_desc for w in ["remote", "დისტანციურ", "სახლიდან", "hybrid"]
        )
        channel, target_email, email_subj = parse_contact_method_and_email(clean_text, raw_html)
        item["channel"] = channel
        item["delivery_channel"] = channel
        item["target_email"] = target_email
        item["email_subject"] = email_subj
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        search_url: Optional[str] = None,
        domain_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        target_url = search_url or self.CATEGORY_IT_QA_URL
        html = await self.fetch_html(target_url)
        if not html:
            return []

        candidates = self.parse_html_listings(html, domain_keywords=domain_keywords)
        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c) for c in candidates[:10]),
            return_exceptions=True,
        )
        return [item for item in enriched if isinstance(item, dict)]


hr_ge_scraper = HrGeScraper()
