import hashlib
import logging
import re
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate, sanitize_company_name
from ..link_validator import parse_vacancy_published_date

logger = logging.getLogger(__name__)
_FEED_HEADERS = {"User-Agent": "TalentFlowAI/2.0 (Remote Job Discovery)"}


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    if "<" not in raw_html:
        return re.sub(r"\s+", " ", raw_html).strip()
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def _matches_domain(title: str, body: str, domain_keywords: Optional[List[str]]) -> bool:
    if not domain_keywords:
        return True
    haystack = f"{title} {body[:1200]}".lower()
    return any(k.lower() in haystack for k in domain_keywords[:14] if k and len(k) >= 2)


class RemotiveScraper(BasePortalScraper):
    """Live Global Remote B2B Scraper using Remotive's public JSON feed."""

    portal_name = "remotive.com"
    API_URL = "https://remotive.com/api/remote-jobs?limit=60"

    async def scrape(
        self,
        allow_network: bool = True,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        payload = await self.fetch_json(self.API_URL, timeout=10.0, headers=_FEED_HEADERS)
        if not isinstance(payload, dict):
            return []

        results: List[Dict[str, Any]] = []
        for job in (payload.get("jobs") or [])[:60]:
            title = str(job.get("title") or "").strip()
            company = sanitize_company_name(job.get("company_name"), fallback="Remotive Employer")
            req_loc = str(job.get("candidate_required_location") or "Worldwide").strip()
            raw_desc = _strip_html(str(job.get("description") or ""))
            sal_raw = str(job.get("salary") or "").strip()
            if not title or not _matches_domain(title, raw_desc, domain_keywords):
                continue

            combined_desc = f"Location: {req_loc} | Contract: {job.get('job_type') or 'Remote'} | {sal_raw}\n{raw_desc}".strip()
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title, description=combined_desc, location_text=req_loc,
                portal=self.portal_name, candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

            pub_dt, pub_str = parse_vacancy_published_date(str(job.get("publication_date") or ""), standalone=True)
            results.append({
                "portal": self.portal_name,
                "external_id": f"remotive-{job.get('id', '')}",
                "title": title,
                "company": company,
                "url": str(job.get("url") or "").strip(),
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": req_loc,
                "channel": "WEB_FORM",
                "detected_languages": langs,
                "language_requirements": langs,
                "description_raw": combined_desc[:4500],
                "posting_date": pub_str,
                "published_at": pub_dt,
                "status": "DISCOVERED",
            })
        return results


class HimalayasScraper(BasePortalScraper):
    """Live Global Remote B2B Scraper using Himalayas' public JSON API."""

    portal_name = "himalayas.app"
    API_URL = "https://himalayas.app/jobs/api?limit=50"

    async def scrape(
        self,
        allow_network: bool = True,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        payload = await self.fetch_json(self.API_URL, timeout=10.0, headers=_FEED_HEADERS)
        if not isinstance(payload, dict):
            return []

        results: List[Dict[str, Any]] = []
        for job in (payload.get("jobs") or [])[:50]:
            title = str(job.get("title") or "").strip()
            company = sanitize_company_name(job.get("companyName"), fallback="Himalayas Employer")
            locs = job.get("locationRestrictions") or []
            loc_str = ", ".join(str(x) for x in locs if x) if isinstance(locs, list) and locs else "Worldwide"
            tzs = job.get("timezoneRestrictions") or []
            tz_str = f"Timezones: {', '.join(str(t) for t in tzs)}" if isinstance(tzs, list) and tzs else ""
            raw_desc = _strip_html(str(job.get("description") or job.get("excerpt") or ""))
            if not title or not _matches_domain(title, raw_desc, domain_keywords):
                continue

            min_s, max_s = job.get("minSalary"), job.get("maxSalary")
            cur = str(job.get("currency") or "USD").strip().upper()
            sal_prefix = f"Salary: {min_s or max_s}-{max_s or min_s} {cur}. " if (min_s or max_s) else ""
            combined_desc = f"{sal_prefix}Allowed Locations: {loc_str}. {tz_str}\n{raw_desc}".strip()
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title, description=combined_desc, location_text=loc_str,
                portal=self.portal_name, candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

            url = str(job.get("guid") or job.get("applicationLink") or "").split("?")[0].strip()
            if not url or not url.startswith(("https://", "http://")):
                continue

            # Deterministic external_id independent of volatile list position
            url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
            pub_dt, pub_str = parse_vacancy_published_date(str(job.get("pubDate") or job.get("createdAt") or ""), standalone=True)
            results.append({
                "portal": self.portal_name,
                "external_id": f"himalayas-{job.get('companySlug') or 'co'}-{url_digest}",
                "title": title,
                "company": company,
                "url": url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": loc_str,
                "channel": "WEB_FORM",
                "detected_languages": langs,
                "language_requirements": langs,
                "description_raw": combined_desc[:4500],
                "posting_date": pub_str,
                "published_at": pub_dt,
                "status": "DISCOVERED",
            })
        return results


class RemoteOkScraper(BasePortalScraper):
    """Live Global Remote & Contractor Scraper using RemoteOK's public JSON API."""

    portal_name = "remoteok.com"
    API_URL = "https://remoteok.com/api"

    async def scrape(
        self,
        allow_network: bool = True,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        items = await self.fetch_json(self.API_URL, timeout=10.0, headers=_FEED_HEADERS)
        if not isinstance(items, list):
            return []

        results: List[Dict[str, Any]] = []
        for job in items:
            if not isinstance(job, dict) or not job.get("position"):
                continue
            if len(results) >= 35:
                break

            title = str(job.get("position") or "").strip()
            company = sanitize_company_name(job.get("company"), fallback="RemoteOK Employer")
            req_loc = str(job.get("location") or "Worldwide").strip() or "Worldwide"
            tags = " ".join(str(t) for t in (job.get("tags") or []) if t)
            raw_desc = _strip_html(str(job.get("description") or ""))
            if not _matches_domain(f"{title} {tags}", raw_desc, domain_keywords):
                continue

            sal_min, sal_max = job.get("salary_min") or 0, job.get("salary_max") or 0
            sal_str = f"Compensation: ${int(sal_min):,} - ${int(sal_max):,} USD. " if sal_min and sal_max else ""
            combined_desc = f"{sal_str}Location: {req_loc}. Tags: {tags}.\n{raw_desc}".strip()
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title, description=combined_desc, location_text=req_loc,
                portal=self.portal_name, candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

            url = str(job.get("url") or job.get("apply_url") or "").strip()
            if url.startswith("/"):
                url = f"https://remoteok.com{url}"
            if not url:
                continue

            pub_dt, pub_str = parse_vacancy_published_date(str(job.get("date") or job.get("epoch") or ""), standalone=True)
            results.append({
                "portal": self.portal_name,
                "external_id": f"remoteok-{job.get('id', '')}",
                "title": title,
                "company": company,
                "url": url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": req_loc,
                "channel": "WEB_FORM",
                "detected_languages": langs,
                "language_requirements": langs,
                "description_raw": combined_desc[:4500],
                "posting_date": pub_str,
                "published_at": pub_dt,
                "status": "DISCOVERED",
            })
        return results


remotive_scraper = RemotiveScraper()
himalayas_scraper = HimalayasScraper()
remoteok_scraper = RemoteOkScraper()
