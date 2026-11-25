import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, parse_contact_method_and_email, sanitize_company_name
from ..link_validator import fetch_and_validate_live_vacancy, parse_vacancy_published_date

logger = logging.getLogger(__name__)


class JobsGeScraper(BasePortalScraper):
    """
    Live Georgian Market Scraper for Jobs.ge.
    Parses #job_list_table rows (including Published Date 'გამოქვეყნდა' and Deadline 'ბოლო ვადა'),
    prioritizes newest postings first, and validates live detail pages.
    """

    portal_name = "jobs.ge"
    market = "GE_DOMESTIC"
    DEFAULT_SEARCH_URLS = [
        "https://jobs.ge/ge/?page=1&cid=6",
        "https://jobs.ge/ge/?page=1&q=QA&cid=6",
        "https://jobs.ge/ge/?page=1&q=Tester&cid=6",
    ]

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        table = soup.select_one("#job_list_table")
        rows = table.find_all("tr") if table else soup.select("table.regularEntries tr, tr")

        for row in rows:
            links = row.find_all("a", href=True)
            job_link = None
            company_text = None
            job_id: Optional[str] = None

            for a in links:
                href = a["href"]
                if "view=client" in href or "client=" in href:
                    txt = a.get_text(" ", strip=True)
                    if txt and not company_text:
                        cand = sanitize_company_name(txt, fallback="")
                        if cand:
                            company_text = cand
                    if not company_text:
                        c_match = re.search(r"client=([a-zA-Z0-9_\-]+)", href)
                        if c_match:
                            c_slug = c_match.group(1).replace("-", " ").replace("_", " ").strip()
                            if c_slug.lower() not in ("all", "jobs", "ge"):
                                company_text = c_slug.upper() if len(c_slug) <= 4 else c_slug.title()
                    continue

                if "view=jobs" in href and "id=" in href:
                    id_m = re.search(r"id=(\d+)", href)
                    txt = a.get_text(strip=True)
                    if id_m and txt and len(txt) >= 3 and not job_link:
                        job_link = a
                        job_id = id_m.group(1)

            if not job_link or not job_id or job_id in seen_ids:
                continue

            title = re.sub(r"\s+NEW\s*$", "", job_link.get_text(" ", strip=True), flags=re.I).strip()
            if len(title) < 3:
                continue

            seen_ids.add(job_id)

            # Extract Published Date (col -2) & Deadline (col -1) from Jobs.ge table cells
            tds = row.find_all("td")
            pub_dt = None
            pub_text = None
            dl_text = None
            if len(tds) >= 5:
                raw_pub = tds[-2].get_text(" ", strip=True)
                raw_dl = tds[-1].get_text(" ", strip=True)
                pub_dt, pub_text = parse_vacancy_published_date(raw_pub, standalone=True)
                if raw_dl and len(raw_dl) >= 4:
                    dl_text = raw_dl

            canonical_url = f"https://jobs.ge/ge/?view=jobs&id={job_id}"
            ext_id = f"jobsge-{job_id}"
            prelim_desc = f"{title} at {company_text or 'Employer'} (Jobs.ge)"
            channel, target_email, email_subj = parse_contact_method_and_email(prelim_desc, str(row))
            company = sanitize_company_name(company_text, target_email=target_email, fallback="კომპანია (Jobs.ge)")

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company,
                "url": canonical_url,
                "market": self.market,
                "is_remote": "remote" in title.lower() or "დისტანციურ" in title.lower(),
                "channel": channel,
                "target_email": target_email,
                "email_subject": email_subj,
                "detected_languages": ["English", "Georgian"],
                "language_requirements": ["English", "Georgian"],
                "description_raw": prelim_desc,
                "posting_date": pub_text,
                "published_at": pub_dt,
                "deadline_text": dl_text,
                "status": "DISCOVERED",
            })

        return results

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetches the live Jobs.ge detail page, rejects blank/expired pages, and extracts body + published date."""
        is_live, clean_text, raw_html = await fetch_and_validate_live_vacancy(item["url"], timeout=9.0)
        if not is_live or not clean_text:
            return None

        if "ინგლისურ ენაზე" in clean_text and "/ge/" in item["url"]:
            en_url = item["url"].replace("/ge/", "/en/")
            en_live, en_text, en_html = await fetch_and_validate_live_vacancy(en_url, timeout=8.0)
            if en_live and len(en_text) > len(clean_text):
                clean_text = f"{clean_text}\n\n{en_text}"
                raw_html = en_html or raw_html

        if not item.get("published_at"):
            pub_dt, pub_text = parse_vacancy_published_date(clean_text, standalone=False)
            if pub_dt:
                item["published_at"] = pub_dt
                item["posting_date"] = pub_text

        item["description_raw"] = clean_text
        item["is_link_live"] = True
        lower_desc = clean_text.lower()
        item["is_remote"] = any(
            w in lower_desc for w in ["remote", "დისტანციურ", "სახლიდან", "hybrid", "worldwide"]
        )

        channel, target_email, email_subj = parse_contact_method_and_email(clean_text, raw_html)
        det_company = ""
        comp_m = re.search(
            r"მომწოდებელი:\s*([^\n<]{2,70}?)(?:\s+(?:გამოქვეყნდა|ბოლო\s+ვადა)|[\r\n]|$)",
            clean_text,
        )
        if comp_m:
            det_company = sanitize_company_name(comp_m.group(1).strip(), target_email=target_email, fallback="")

        client_slug_comp = ""
        if raw_html:
            soup_det = self.make_soup(raw_html)
            for client_a in soup_det.select("td.dtable a[href*='view=client'], .dtable a[href*='view=client'], a[href*='client=']"):
                cand = sanitize_company_name(client_a.get_text(" ", strip=True), target_email=target_email, fallback="")
                if cand:
                    det_company = cand
                    break
            c_slug_m = re.search(r"client=([a-zA-Z0-9_\-]+)", raw_html)
            if c_slug_m:
                c_s = c_slug_m.group(1).replace("-", " ").replace("_", " ").strip()
                if c_s.lower() not in ("all", "jobs", "ge"):
                    client_slug_comp = c_s.upper() if len(c_s) <= 4 else c_s.title()

        table_company = sanitize_company_name(item.get("company"), target_email=target_email, fallback="")
        item["company"] = det_company or table_company or client_slug_comp or sanitize_company_name(None, target_email=target_email, fallback="კომპანია (Jobs.ge)")
        item["channel"] = channel
        item["delivery_channel"] = channel
        item["target_email"] = target_email
        item["email_subject"] = email_subj
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        search_urls: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        urls = search_urls or self.DEFAULT_SEARCH_URLS
        return await self.scrape_and_enrich_urls(
            urls,
            self.parse_html_listings,
            self._enrich_and_verify_item,
            limit=18,
            page_timeout=10.0,
            sort_newest_first=True,
        )


jobs_ge_scraper = JobsGeScraper()
