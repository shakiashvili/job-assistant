import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, parse_contact_method_and_email
from ..link_validator import fetch_and_validate_live_vacancy

logger = logging.getLogger(__name__)


class JobsGeScraper(BasePortalScraper):
    """
    Live Georgian Market Scraper for Jobs.ge.
    Searches dynamically based on candidate's target role from skills.md:
      - e.g., https://jobs.ge/ge/?page=1&q=QA&cid=6 and ?q=Tester&cid=6
    Parses strictly from #job_list_table <tr> rows, constructs canonical URLs
    https://jobs.ge/ge/?view=jobs&id={job_id}, and validates every vacancy detail page
    with a live HTTP GET health check (preventing blank/expired 200 OK pages).
    """

    portal_name = "jobs.ge"
    market = "GE_DOMESTIC"
    DEFAULT_SEARCH_URLS = [
        "https://jobs.ge/ge/?page=1&q=QA&cid=6",
        "https://jobs.ge/ge/?page=1&q=Tester&cid=6",
    ]

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Parse ONLY inside #job_list_table (ignore VIP banners, logos, and sidebars)
        table = soup.select_one("#job_list_table")
        if table:
            rows = table.find_all("tr")
        else:
            # Support direct unit-test HTML fixtures if #job_list_table isn't wrapped
            rows = soup.select("table.regularEntries tr, tr")

        for row in rows:
            links = row.find_all("a", href=True)
            job_link = None
            company_text = None
            job_id: Optional[str] = None

            for a in links:
                href = a["href"]
                # Ignore client profile links, images, and non-vacancy links
                if "view=client" in href or "client=" in href:
                    txt = a.get_text(strip=True)
                    if txt and not company_text:
                        company_text = txt
                    continue

                if "view=jobs" in href and "id=" in href:
                    id_m = re.search(r"id=(\d+)", href)
                    txt = a.get_text(strip=True)
                    if id_m and txt and len(txt) >= 3 and not job_link:
                        job_link = a
                        job_id = id_m.group(1)

            if not job_link or not job_id or job_id in seen_ids:
                continue

            title = job_link.get_text(strip=True)
            if len(title) < 3:
                continue

            seen_ids.add(job_id)

            # Enforce strict canonical Jobs.ge URL format
            canonical_url = f"https://jobs.ge/ge/?view=jobs&id={job_id}"
            ext_id = f"jobsge-{job_id}"

            if not company_text:
                tds = [td.get_text(strip=True) for td in row.find_all("td") if td.get_text(strip=True)]
                if len(tds) >= 2:
                    company_text = tds[1] if tds[0] == title else tds[-1]
            company = company_text or "Georgian Employer"

            # Preliminary placeholder description; live scraper overwrites with full detail page text
            prelim_desc = f"{title} at {company} (Jobs.ge)"
            channel, target_email, email_subj = parse_contact_method_and_email(prelim_desc, str(row))

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
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        """Purged: never inject dead/mock vacancies when network fails or is disabled."""
        return []

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetches the live Jobs.ge detail page, rejects blank/expired pages, and extracts real body."""
        is_live, clean_text, raw_html = await fetch_and_validate_live_vacancy(item["url"], timeout=8.0)
        if not is_live or not clean_text:
            return None

        # If Georgian listing redirects/defers full description to English version, fetch English text
        if "ინგლისურ ენაზე" in clean_text and "/ge/" in item["url"]:
            en_url = item["url"].replace("/ge/", "/en/")
            en_live, en_text, en_html = await fetch_and_validate_live_vacancy(en_url, timeout=8.0)
            if en_live and len(en_text) > len(clean_text):
                clean_text = f"{clean_text}\n\n{en_text}"
                raw_html = en_html or raw_html

        item["description_raw"] = clean_text
        item["is_link_live"] = True
        lower_desc = clean_text.lower()
        item["is_remote"] = any(
            w in lower_desc for w in ["remote", "დისტანციურ", "სახლიდან", "hybrid", "worldwide"]
        )

        channel, target_email, email_subj = parse_contact_method_and_email(clean_text, raw_html)
        # Extract authentic company name from detail page 'მომწოდებელი:' if table fell back
        comp_m = re.search(r"მომწოდებელი:\s*([^\n<]{2,60}?)(?:\s+გამოქვეყნდა|\s*$)", clean_text)
        if comp_m and item.get("company") in ("Georgian Employer", "Company", ""):
            item["company"] = comp_m.group(1).strip()

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
        html_pages = await asyncio.gather(*(self.fetch_html(u) for u in urls), return_exceptions=True)

        candidates: List[Dict[str, Any]] = []
        seen_ext_ids: set[str] = set()
        for html in html_pages:
            if isinstance(html, str) and html:
                for parsed in self.parse_html_listings(html):
                    if parsed["external_id"] not in seen_ext_ids:
                        seen_ext_ids.add(parsed["external_id"])
                        candidates.append(parsed)

        if not candidates:
            return []

        # Live health-check and full text enrichment concurrently (cap to top 20 listings)
        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c) for c in candidates[:20]),
            return_exceptions=True,
        )
        return [item for item in enriched if isinstance(item, dict)]


jobs_ge_scraper = JobsGeScraper()
