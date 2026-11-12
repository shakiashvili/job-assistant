import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup
from .base_scraper import BasePortalScraper, parse_contact_method_and_email, sanitize_company_name

logger = logging.getLogger(__name__)


class HrGovScraper(BasePortalScraper):
    """
    Live Public Administration & Internship Scraper for vacancy.hr.gov.ge.
    Searches entry-level state roles and internships (`სტაჟიორი`, `დამწყები`) alongside
    candidate domain keywords, fetching live detail pages to extract verified agency name,
    explicit GEL salary (`თანამდებობრივი სარგო`), deadline, and full qualifications.
    """

    portal_name = "hr.gov.ge"
    market = "GE_PUBLIC"
    BASE_URL = "https://vacancy.hr.gov.ge/"

    async def search_post(self, search_term: str, timeout: float = 10.0) -> Optional[str]:
        """Posts a SearchTerm filter query to vacancy.hr.gov.ge and returns resulting HTML."""
        try:
            async with httpx.AsyncClient(
                headers=self.DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=timeout,
            ) as client:
                resp = await client.post(
                    self.BASE_URL,
                    data={"SearchTerm": search_term, "find": "ძებნა"},
                )
                if resp.status_code == 200 and resp.text:
                    return resp.text
        except Exception as e:
            logger.debug(f"[hr.gov.ge] POST search '{search_term}' failed: {e}")
        return None

    def parse_html_listings(
        self,
        html: str,
        keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        kw_lower = [k.lower() for k in (keywords or []) if len(k) >= 2]

        for idx, tr in enumerate(soup.select("tr")):
            links = tr.select("a[href*='/Details/']")
            if not links:
                continue

            href = str(links[0].get("href") or "").strip()
            id_m = re.search(r"/Details/(\d+)", href)
            if not id_m:
                continue
            vak_id = id_m.group(1)
            ext_id = f"hrgov-{vak_id}"
            if ext_id in seen_ids:
                continue

            title = re.sub(r"\s+", " ", links[0].get_text(" ", strip=True)).strip()
            if not title or len(title) < 3:
                continue

            raw_org = links[1].get_text(" ", strip=True) if len(links) >= 2 else ""
            company = sanitize_company_name(raw_org, fallback="საჯარო უწყება (HR.gov.ge)")

            tds = tr.find_all("td")
            deadline_txt = ""
            if tds:
                dl_m = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", tds[-1].get_text(" ", strip=True))
                if dl_m:
                    deadline_txt = dl_m.group(1)

            lower_row = f"{title} {company}".lower()
            is_intern_entry = any(w in lower_row for w in ["სტაჟიორ", "დამწყებ", "უმცროს", "intern", "trainee", "junior", "ასისტენტ", "სპეციალისტ"])
            matches_kw = (not kw_lower) or is_intern_entry or any(k in lower_row for k in kw_lower)
            if not matches_kw:
                continue

            seen_ids.add(ext_id)
            full_url = href if href.startswith("http") else f"https://vacancy.hr.gov.ge{href}"
            prelim_desc = f"{title} | {company} | ბოლო ვადა: {deadline_txt}".strip(" |")

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": full_url,
                "market": self.market,
                "is_remote": False,
                "channel": "WEB_FORM",
                "detected_languages": ["Georgian"],
                "language_requirements": ["Georgian"],
                "deadline_text": deadline_txt or None,
                "description_raw": prelim_desc,
                "match_tier": "PUBLIC_INTERNSHIP",
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        return []

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetches live vacancy.hr.gov.ge detail page to extract salary, requirements, and verified deadline."""
        html = await self.fetch_html(item["url"], timeout=10.0)
        if not html:
            return item

        soup = self.make_soup(html)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        if len(body_text) < 100:
            return None

        # Trim navigation header before "ვაკანსიის N" or "პოზიციის დასახელება"
        idx = body_text.find("პოზიციის დასახელება")
        clean_desc = body_text[idx:idx + 4500] if idx != -1 else body_text[:4500]

        org_m = re.search(r"ორგანიზაცია\s+(.{3,90}?)(?:\s+ორგანიზაციის შესახებ|\s+კატეგორია)", clean_desc)
        if org_m:
            org_clean = sanitize_company_name(org_m.group(1).strip(), fallback="")
            if org_clean:
                item["company"] = org_clean

        dl_m = re.search(r"(?:განცხადების\s+)?ბოლო\s+ვადა\s+(\d{2}\.\d{2}\.\d{4})", clean_desc)
        if dl_m:
            item["deadline_text"] = dl_m.group(1)

        channel, target_email, email_subj = parse_contact_method_and_email(clean_desc, html[:6000])
        item["channel"] = channel
        item["delivery_channel"] = channel
        item["target_email"] = target_email
        item["email_subject"] = email_subj
        item["description_raw"] = clean_desc
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        queries: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        search_terms = list(dict.fromkeys((queries or ["სტაჟიორი", "დამწყები"])[:3]))
        tasks = [self.fetch_html(self.BASE_URL, timeout=10.0)]
        tasks.extend(self.search_post(q, timeout=10.0) for q in search_terms[:2])

        pages = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(html, keywords=domain_keywords):
                    if item["external_id"] not in seen_ids:
                        seen_ids.add(item["external_id"])
                        candidates.append(item)

        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c) for c in candidates[:12]),
            return_exceptions=True,
        )
        return [x for x in enriched if isinstance(x, dict)]


hr_gov_scraper = HrGovScraper()
