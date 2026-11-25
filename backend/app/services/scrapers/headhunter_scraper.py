import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import (
    BasePortalScraper,
    evaluate_remote_and_language_gate,
    matches_domain_keywords,
    parse_contact_method_and_email,
    parse_portal_published_at,
    sanitize_company_name,
)

logger = logging.getLogger(__name__)


class HeadhunterScraper(BasePortalScraper):
    """
    Live Georgia & Regional Multi-Industry Scraper for headhunter.ge.
    Extracts live vacancies across any profession (area=28 Georgia, sorted by publication_time),
    parses publication dates, verifies detail descriptions, and applies spoken-language gates.
    """

    portal_name = "headhunter.ge"
    market = "GE_DOMESTIC"
    SEARCH_URL = "https://headhunter.ge/search/vacancy?text=QA&area=28&order_by=publication_time"

    def parse_html_listings(
        self,
        html: str,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        cards = soup.select("[data-qa='vacancy-serp__vacancy']")
        if not cards:
            seen_parents = set()
            cards = []
            for a_tag in soup.select("a[href*='/vacancy/']"):
                p = a_tag.parent.parent if a_tag.parent and a_tag.parent.parent else a_tag.parent
                if p and id(p) not in seen_parents:
                    seen_parents.add(id(p))
                    cards.append(p)

        for idx, item in enumerate(cards):
            title_el = item.select_one(
                "a[data-qa='serp-item__title'], [data-qa='serp-item__title'], [data-qa='vacancy-serp__vacancy-title'], a[href*='/vacancy/']"
            )
            if not title_el:
                continue
            href_raw = title_el.get("href") or (title_el.find("a", href=True) or {}).get("href")
            if not href_raw:
                continue

            href = str(href_raw).split("?")[0]
            if "/vacancy/" not in href:
                continue
            url = href if href.startswith("http") else f"https://headhunter.ge{href}"

            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)).strip()
            if not title or len(title) < 3:
                continue

            if domain_keywords and not matches_domain_keywords(title, domain_keywords):
                continue

            id_match = re.search(r"/vacancy/(\d+)", url)
            ext_id = f"hh-{id_match.group(1)}" if id_match else f"hh-row-{idx}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            comp_el = item.select_one(
                "[data-qa='vacancy-serp__vacancy-employer'], [data-qa='vacancy-serp__vacancy-employer-text'], a[href*='/employer/']"
            )
            raw_company = comp_el.get_text(" ", strip=True) if comp_el else ""
            company = sanitize_company_name(raw_company, fallback="HeadHunter Employer")

            loc_el = item.select_one("[data-qa='vacancy-serp__vacancy-address']")
            location_text = loc_el.get_text(" ", strip=True) if loc_el else "Tbilisi, Georgia"

            sal_el = item.select_one("[data-qa*='compensation']")
            sal_text = sal_el.get_text(" ", strip=True) if sal_el else ""

            dt_el = item.select_one("[data-qa='vacancy-serp__vacancy-date']")
            pub_dt, pub_str = parse_portal_published_at(dt_el.get_text(" ", strip=True) if dt_el else None)

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
                "published_at": pub_dt,
                "posting_date": pub_str,
                "description_raw": desc_body[:4000],
                "status": status,
                "filter_out_reason": filter_reason or None,
                "match_rationale": filter_reason,
            })

        return results

    async def _enrich_and_verify_item(
        self,
        item: Dict[str, Any],
        candidate_languages: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetches live detail page, extracts full description, publication date, contact email, and language gate."""
        html = await self.fetch_html(item["url"], timeout=7.0)
        if not html:
            return item

        soup = self.make_soup(html)
        desc_el = soup.select_one("[data-qa='vacancy-description']")
        body_text = desc_el.get_text(" ", strip=True) if desc_el else ""
        if len(body_text) < 40:
            return item

        # Extract exact datePosted from meta / JSON-LD / creation-time label
        if not item.get("published_at"):
            dp_m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', html)
            dt_el = soup.select_one("[data-qa='vacancy-view-creation-time']")
            raw_dt = dp_m.group(1) if dp_m else (dt_el.get_text(" ", strip=True) if dt_el else None)
            pub_dt, pub_str = parse_portal_published_at(raw_dt)
            if pub_dt:
                item["published_at"] = pub_dt
                item["posting_date"] = pub_str

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
        base_urls = search_urls or [search_url or self.SEARCH_URL]
        return await self.scrape_and_enrich_urls(
            base_urls,
            lambda html: self.parse_html_listings(
                html, domain_keywords=domain_keywords, candidate_languages=candidate_languages
            ),
            lambda c: self._enrich_and_verify_item(c, candidate_languages=candidate_languages),
            limit=18,
            dedupe_title_company=True,
            page_timeout=10.0,
            sort_newest_first=True,
        )


headhunter_scraper = HeadhunterScraper()
