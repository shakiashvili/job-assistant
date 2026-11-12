import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, parse_contact_method_and_email, sanitize_company_name
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

            comp_el = item.select_one(".company, .employer-name, .company-title, a[href*='/company/']")
            company = comp_el.get_text(" ", strip=True) if comp_el else ""
            if not company and item.parent:
                # Infer employer from card sibling spans if link doesn't embed it
                cand_texts = [
                    x.get_text(" ", strip=True)
                    for x in item.parent.select("a[href*='/company/'], span, div")
                    if x.get_text(" ", strip=True) and x.get_text(" ", strip=True) != title
                ]
                for ct in cand_texts:
                    clean_ct = sanitize_company_name(ct, fallback="")
                    if clean_ct and 2 <= len(clean_ct) <= 45 and not re.search(r"ვიპ|vip", clean_ct, re.I):
                        company = clean_ct
                        break

            full_url = href if href.startswith("http") else f"https://www.hr.ge/{href.lstrip('/')}"
            id_match = re.search(r"announcement/(\d+)", full_url)
            ext_id = f"hrge-{id_match.group(1)}" if id_match else f"hrge-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            prelim_desc = f"{title} at {company or 'Employer'} (HR.ge)"
            channel, target_email, email_subj = parse_contact_method_and_email(prelim_desc, str(item))
            company = sanitize_company_name(company, target_email=target_email, fallback="კომპანია (HR.ge)")

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
        soup_det = self.make_soup(raw_html)
        comp_det = soup_det.select_one("a[href*='/company/'], .company-name, .employer-name, [itemprop='hiringOrganization']")
        det_comp_txt = comp_det.get_text(" ", strip=True) if comp_det else ""
        item["company"] = sanitize_company_name(
            det_comp_txt or item.get("company"),
            target_email=target_email,
            fallback="კომპანია (HR.ge)",
        )

        item["channel"] = channel
        item["delivery_channel"] = channel
        item["target_email"] = target_email
        item["email_subject"] = email_subj
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        search_url: Optional[str] = None,
        search_urls: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        urls = search_urls or ([search_url] if search_url else [self.CATEGORY_IT_QA_URL])
        pages = await asyncio.gather(*(self.fetch_html(u) for u in urls), return_exceptions=True)

        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(html, domain_keywords=domain_keywords):
                    if item["external_id"] not in seen_ids:
                        seen_ids.add(item["external_id"])
                        candidates.append(item)

        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c) for c in candidates[:18]),
            return_exceptions=True,
        )
        return [item for item in enriched if isinstance(item, dict)]


hr_ge_scraper = HrGeScraper()
