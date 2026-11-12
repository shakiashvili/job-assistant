import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from urllib.parse import quote_plus
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate, sanitize_company_name

logger = logging.getLogger(__name__)

_SENIOR_TITLE_PATTERN = re.compile(
    r"\b(?:senior|sr\.?|lead|principal|staff|architect|director|vp|head\s+of|chief|manager|iii|iv)\b",
    re.IGNORECASE,
)


def build_linkedin_search_urls(
    primary_role: str,
    verified_skills: Optional[List[str]] = None,
    cap_exp: float = 2.0,
) -> List[str]:
    """
    Constructs targeted LinkedIn public guest search URLs dynamically filtered by experience level:
    f_E=1,2,3 (Internship, Entry level, Associate) and Remote / Georgia markets.
    """
    role = (primary_role or "Specialist").strip()
    clean_kw = re.sub(r"[/|]+", " ", role).strip()
    words = [w for w in clean_kw.split() if len(w) >= 2]
    kw_primary = " ".join(words[:3]) if words else "Junior"
    skills = [s for s in (verified_skills or []) if s and len(s) >= 2]

    # f_E=1%2C2%2C3 => Internship (1), Entry level (2), Associate (3)
    exp_filter = "1%2C2" if cap_exp <= 1.0 else "1%2C2%2C3"
    urls = [
        f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(kw_primary)}&f_E={exp_filter}&f_WT=2",
        f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(kw_primary)}&location=Georgia&f_E={exp_filter}",
    ]
    if skills:
        alt_kw = f"{words[0]} {skills[0]}" if words else skills[0]
        urls.append(
            f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(alt_kw)}&f_E={exp_filter}&f_WT=2"
        )
    return list(dict.fromkeys(urls))


class LinkedInScraper(BasePortalScraper):
    """
    LinkedIn Job Discovery Scraper (Guest Search + Easy Apply / External ATS Tagging):
    - Uses targeted URL parameters (f_E=1,2,3 Entry/Associate/Intern & f_WT=2 Remote).
    - Parses LinkedIn public job cards and optional guest job-detail snippets.
    - Detects delivery_channel: EASY_APPLY vs EXTERNAL_ATS.
    - Enforces strict Senior/Lead/3+ yr experience rejection before ingestion.
    - Fails gracefully (returns []) if LinkedIn rate-limits unauthenticated requests.
    """

    portal_name = "linkedin.com"
    market = "GLOBAL_REMOTE"
    SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords=Junior+QA+Engineer&f_E=1%2C2%2C3&f_WT=2"

    def parse_html_listings(
        self,
        html: str,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        cards = soup.select(
            "div.job-search-card, div.base-card, li.jobs-search-results__list-item"
        )
        for idx, card in enumerate(cards):
            title_el = card.select_one(
                "h3.base-search-card__title, .job-card-list__title, h3"
            )
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title or len(title) < 3:
                continue

            link_el = card.select_one(
                "a.base-card__full-link, a.job-card-container__link, a[href*='/jobs/view/']"
            )
            raw_href = (link_el.get("href") or "").strip() if link_el else ""
            if not raw_href:
                continue
            url = raw_href.split("?")[0]
            if not url.startswith("http"):
                url = f"https://www.linkedin.com{url}"

            comp_el = card.select_one(
                "h4.base-search-card__subtitle a, h4.base-search-card__subtitle, .job-card-container__company-name, h4"
            )
            raw_comp = comp_el.get_text(" ", strip=True) if comp_el else ""
            company = sanitize_company_name(raw_comp, fallback="LinkedIn Employer")

            loc_el = card.select_one(
                "span.job-search-card__location, .job-card-container__metadata-item"
            )
            location_text = loc_el.get_text(" ", strip=True) if loc_el else "Remote"

            card_blob = card.get_text(" ", strip=True)
            is_easy_apply = bool(
                re.search(r"\beasy\s+apply\b", card_blob, re.IGNORECASE)
                or card.select_one(".job-card-container__apply-method, .jobs-apply-button")
            )
            delivery_channel = "EASY_APPLY" if is_easy_apply else "EXTERNAL_ATS"

            id_match = re.search(r"/jobs/view/(?:[^/?-]+-)*?(\d+)", url)
            if not id_match:
                urn = card.get("data-entity-urn") or ""
                id_match = re.search(r"(\d+)$", urn)
            raw_id = id_match.group(1) if id_match else f"card-{idx}"
            ext_id = f"linkedin-{raw_id}"
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)

            is_remote, status, reason, langs = evaluate_remote_and_language_gate(
                title=title,
                description=f"{card_blob}\n{location_text}",
                location_text=location_text,
                portal="linkedin.com",
                candidate_languages=candidate_languages,
            )

            if _SENIOR_TITLE_PATTERN.search(title):
                status = "FILTERED_OUT"
                reason = f"Strict Experience Cap: Role '{title}' exceeds <= 2.0 yrs Junior/Associate limit."

            market_tag = (
                "GE_DOMESTIC"
                if "georgia" in location_text.lower() or "tbilisi" in location_text.lower()
                else ("GLOBAL_REMOTE" if is_remote else "INT_HYBRID")
            )

            results.append(
                {
                    "portal": self.portal_name,
                    "external_id": ext_id,
                    "raw_job_id": raw_id if id_match else None,
                    "url": url,
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "market": market_tag,
                    "description_raw": (
                        f"LinkedIn {delivery_channel} | {title} at {company} | Location: {location_text}\n"
                        f"{card_blob[:800]}"
                    ),
                    "delivery_channel": delivery_channel,
                    "is_remote": is_remote,
                    "status": status,
                    "filter_out_reason": reason,
                    "detected_languages": langs,
                }
            )

        return results

    async def _enrich_card_details(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort fetch of LinkedIn guest jobPosting detail HTML to inspect full requirements & salary."""
        raw_id = job.get("raw_job_id")
        if not raw_id:
            return job
        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{raw_id}"
        html = await self.fetch_html(detail_url, timeout=8.0)
        if not html:
            return job

        soup = self.make_soup(html)
        desc_el = soup.select_one(
            "div.show-more-less-html__markup, div.description__text"
        )
        if desc_el:
            full_desc = desc_el.get_text(" ", strip=True)
            job["description_raw"] = (
                f"LinkedIn {job.get('delivery_channel', 'EXTERNAL_ATS')} | "
                f"{job['title']} at {job['company']} | Location: {job['location']}\n"
                f"{full_desc[:3500]}"
            )
            if re.search(r"\b(?:[3-9]|1[0-9])\+?\s*(?:years?|yrs?)\b", full_desc, re.IGNORECASE):
                job["status"] = "FILTERED_OUT"
                job["filter_out_reason"] = "Strict Experience Cap: LinkedIn job description requires 3+ years."
        return job

    async def scrape(
        self,
        allow_network: bool = True,
        search_urls: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        urls = search_urls or [self.SEARCH_URL]
        raw_jobs: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for u in urls[:3]:
            html = await self.fetch_html(u, timeout=10.0)
            if not html:
                continue
            parsed = self.parse_html_listings(html, candidate_languages=candidate_languages)
            for item in parsed:
                if item["external_id"] in seen_ids:
                    continue
                seen_ids.add(item["external_id"])
                if domain_keywords:
                    blob = f"{item['title']} {item['description_raw']}".lower()
                    if not any(kw.lower() in blob for kw in domain_keywords):
                        continue
                raw_jobs.append(item)

        if not raw_jobs:
            return []

        # Enrich top non-filtered cards with full descriptions (polite concurrency)
        candidates = [j for j in raw_jobs if j.get("status") != "FILTERED_OUT"][:6]
        if candidates:
            await asyncio.gather(*(self._enrich_card_details(j) for j in candidates), return_exceptions=True)

        for j in raw_jobs:
            j.pop("raw_job_id", None)

        return raw_jobs


linkedin_scraper = LinkedInScraper()
