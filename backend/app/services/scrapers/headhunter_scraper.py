import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import (
    BasePortalScraper,
    evaluate_remote_and_language_gate,
    parse_contact_method_and_email,
    sanitize_company_name,
)

logger = logging.getLogger(__name__)


class HeadhunterScraper(BasePortalScraper):
    """
    Live Georgia & Regional Tech Scraper for headhunter.ge (tbilisi.headhunter.ge).
    Extracts real live vacancies matching the candidate's target role keywords, verifies
    detail descriptions live, and gates Russian-language vacancies by candidate_languages.
    """

    portal_name = "headhunter.ge"
    market = "GE_DOMESTIC"
    SEARCH_URL = "https://tbilisi.headhunter.ge/search/vacancy?text=QA&area=28"

    def parse_html_listings(
        self,
        html: str,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        kw_list = [
            k.lower()
            for k in (domain_keywords or ["qa", "quality assurance", "tester", "test", "sdet", "ტესტ"])
        ]

        cards = soup.select("[data-qa='vacancy-serp__vacancy']")
        if not cards:
            # Fallback wrapper detection around HH vacancy links
            seen_parents = set()
            cards = []
            for a_tag in soup.select("a[href*='/vacancy/']"):
                p = a_tag.parent.parent if a_tag.parent and a_tag.parent.parent else a_tag.parent
                if p and id(p) not in seen_parents:
                    seen_parents.add(id(p))
                    cards.append(p)

        for idx, item in enumerate(cards):
            title_el = item.select_one(
                "[data-qa='serp-item__title'], [data-qa='vacancy-serp__vacancy-title'], a[href*='/vacancy/']"
            )
            if not title_el or not title_el.get("href"):
                continue

            href = str(title_el["href"]).split("?")[0]
            if "/vacancy/" not in href:
                continue
            url = href if href.startswith("http") else f"https://tbilisi.headhunter.ge{href}"

            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)).strip()
            if not title or len(title) < 3:
                continue

            # Keep IT/QA search results relevant
            lower_title = title.lower()
            if not any(kw in lower_title for kw in kw_list):
                continue

            id_match = re.search(r"/vacancy/(\d+)", url)
            ext_id = f"hh-{id_match.group(1)}" if id_match else f"hh-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            comp_el = item.select_one("[data-qa='vacancy-serp__vacancy-employer'], a[href*='/employer/']")
            raw_company = comp_el.get_text(" ", strip=True) if comp_el else ""
            company = sanitize_company_name(raw_company, fallback="HeadHunter Employer")

            loc_el = item.select_one("[data-qa='vacancy-serp__vacancy-address']")
            location_text = loc_el.get_text(" ", strip=True) if loc_el else "Tbilisi, Georgia"

            sal_el = item.select_one("[data-qa*='compensation']")
            sal_text = sal_el.get_text(" ", strip=True) if sal_el else ""

            snip_parts = [
                el.get_text(" ", strip=True)
                for el in item.select("[data-qa*='snippet'], [data-qa='vacancy-serp__vacancy-work-schedule']")
                if el.get_text(" ", strip=True)
            ]
            desc_body = " | ".join([p for p in [sal_text, location_text] + snip_parts if p]) or title
            is_remote_card = bool(re.search(r"\b(remote|удаленн|удалённ|hybrid|გიბრიდ|დისტანციურ)\b", desc_body, re.I))

            is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc_body,
                location_text=location_text,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )

            channel, target_email, email_subj = parse_contact_method_and_email(desc_body, str(item))

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": url,
                "market": self.market,
                "is_remote": is_remote or is_remote_card,
                "location_meta": location_text,
                "channel": channel,
                "target_email": target_email,
                "email_subject": email_subj,
                "detected_languages": langs,
                "language_requirements": langs,
                "description_raw": desc_body[:4000],
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
        """Fetches live detail page, extracts full description, contact email, and language gate."""
        html = await self.fetch_html(item["url"], timeout=8.0)
        if not html:
            return item

        soup = self.make_soup(html)
        desc_el = soup.select_one("[data-qa='vacancy-description']")
        body_text = desc_el.get_text(" ", strip=True) if desc_el else ""
        if len(body_text) < 40:
            return item

        sal_el = soup.select_one("[data-qa='vacancy-salary']")
        sal_txt = sal_el.get_text(" ", strip=True) if sal_el else ""

        comp_el = soup.select_one("[data-qa='vacancy-company-name'], a[data-qa='vacancy-company-name']")
        if comp_el and comp_el.get_text(strip=True):
            cleaned_comp = sanitize_company_name(comp_el.get_text(" ", strip=True), fallback="")
            if cleaned_comp:
                item["company"] = cleaned_comp

        full_desc = f"{sal_txt} | {body_text}".strip(" |") if sal_txt else body_text
        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=body_text,
            location_text=item.get("location_meta") or "Tbilisi, Georgia",
            portal=self.portal_name,
            candidate_languages=candidate_languages,
        )

        channel, target_email, email_subj = parse_contact_method_and_email(
            full_desc, str(desc_el) if desc_el else html[:5000]
        )
        if target_email:
            item["channel"] = "EMAIL"
            item["target_email"] = target_email
            if email_subj:
                item["email_subject"] = email_subj
        else:
            item["channel"] = item.get("channel") or "WEB_FORM"

        item["is_remote"] = is_remote or bool(
            re.search(r"\b(remote|удаленн|удалённ|გიბრიდ|დისტანციურ)\b", full_desc, re.I)
        )
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
        search_urls: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        base_urls = search_urls or [
            search_url or self.SEARCH_URL,
        ]
        pages = await asyncio.gather(*(self.fetch_html(u) for u in base_urls), return_exceptions=True)

        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_title_comp: set[tuple[str, str]] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(
                    html,
                    domain_keywords=domain_keywords,
                    candidate_languages=candidate_languages,
                ):
                    tc_key = (item["title"].lower().strip(), item["company"].lower().strip())
                    if item["external_id"] not in seen_ids and tc_key not in seen_title_comp:
                        seen_ids.add(item["external_id"])
                        seen_title_comp.add(tc_key)
                        candidates.append(item)

        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c, candidate_languages=candidate_languages) for c in candidates[:18]),
            return_exceptions=True,
        )
        return [x for x in enriched if isinstance(x, dict)]


headhunter_scraper = HeadhunterScraper()
