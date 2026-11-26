import json
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import (
    BasePortalScraper,
    matches_domain_keywords,
    parse_contact_method_and_email,
    parse_portal_published_at,
    sanitize_company_name,
)
from ..link_validator import fetch_and_validate_live_vacancy

logger = logging.getLogger(__name__)


def _find_ng_state_announcements(obj: Any) -> Optional[List[Dict[str, Any]]]:
    """Recursively locates HR.ge's embedded Angular ng-state announcements list."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "publishDate" in obj[0] and "title" in obj[0]:
        return obj
    if isinstance(obj, dict):
        for val in obj.values():
            found = _find_ng_state_announcements(val)
            if found:
                return found
    return None


class HrGeScraper(BasePortalScraper):
    """
    Live Georgian Market Scraper for HR.ge.
    Parses embedded Angular ng-state JSON (with exact publishDate, deadlineDate, company, locations)
    with HTML fallback, filters by word-boundary domain keywords, and sorts newest-first.
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
        kw_list = domain_keywords if domain_keywords is not None else None

        # Fast structured path: HR.ge Angular SSR <script id="ng-state"> JSON payload
        ng_script = soup.find("script", id="ng-state")
        if ng_script and ng_script.string:
            try:
                ng_data = json.loads(ng_script.string)
                anns = _find_ng_state_announcements(ng_data) or []
                for idx, ann in enumerate(anns):
                    title = re.sub(r"\s+", " ", str(ann.get("title") or "")).strip()
                    if not title or len(title) < 3:
                        continue
                    if kw_list and not matches_domain_keywords(title, kw_list):
                        continue
                    ann_id = ann.get("announcementId") or ann.get("id")
                    ext_id = f"hrge-{ann_id}" if ann_id else f"hrge-ng-{idx}"
                    if ext_id in seen_ids:
                        continue
                    seen_ids.add(ext_id)
                    company = sanitize_company_name(ann.get("customerName"), fallback="კომპანია (HR.ge)")
                    locs = ann.get("locations") or []
                    loc_str = ", ".join(str(x) for x in locs if x) or "Tbilisi, Georgia"
                    pub_dt, pub_str = parse_portal_published_at(ann.get("publishDate"))
                    _, dl_str = parse_portal_published_at(ann.get("deadlineDate"))
                    full_url = f"https://www.hr.ge/announcement/{ann_id}" if ann_id else "https://www.hr.ge/"
                    prelim_desc = f"{title} | {company} | {loc_str} (HR.ge)"
                    results.append({
                        "portal": self.portal_name,
                        "external_id": ext_id,
                        "title": title,
                        "company": company,
                        "url": full_url,
                        "market": self.market,
                        "is_remote": any(w in f"{title} {loc_str}".lower() for w in ("remote", "დისტანციურ")),
                        "location_meta": loc_str,
                        "channel": "WEB_FORM",
                        "target_email": None,
                        "email_subject": None,
                        "detected_languages": ["English", "Georgian"],
                        "language_requirements": ["English", "Georgian"],
                        "published_at": pub_dt,
                        "posting_date": pub_str,
                        "deadline_text": dl_str,
                        "description_raw": prelim_desc,
                        "status": "DISCOVERED",
                    })
                if results:
                    return results
            except Exception as exc:
                logger.debug("[hr.ge] ng-state parse fallback: %s", exc)

        # HTML fallback (for pages without ng-state or unit-test fixtures)
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

            if kw_list and not matches_domain_keywords(title, kw_list):
                continue

            comp_el = item.select_one(".company, .employer-name, .company-title, a[href*='/company/']")
            company = comp_el.get_text(" ", strip=True) if comp_el else ""
            if not company and item.parent:
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

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        is_live, clean_text, raw_html = await fetch_and_validate_live_vacancy(item["url"], timeout=6.0)
        if not is_live or not clean_text:
            # Keep structured ng-state items that already have verified publishDate & company
            return item if item.get("published_at") else None

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
        return await self.scrape_and_enrich_urls(
            urls,
            lambda html: self.parse_html_listings(html, domain_keywords=domain_keywords),
            self._enrich_and_verify_item,
            limit=18,
            page_timeout=10.0,
            sort_newest_first=True,
        )


hr_ge_scraper = HrGeScraper()
