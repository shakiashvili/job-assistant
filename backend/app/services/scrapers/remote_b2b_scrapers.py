import logging
import re
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup

from .base_scraper import evaluate_remote_and_language_gate, sanitize_company_name
from ..salary_service import salary_service

logger = logging.getLogger(__name__)


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


class RemotiveScraper:
    """
    Live Global Remote B2B Scraper using Remotive's public JSON feed
    (https://remotive.com/api/remote-jobs).
    """

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

        results: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    self.API_URL,
                    headers={"User-Agent": "TalentFlowAI/2.0 (Remote Job Discovery)"},
                )
                if resp.status_code != 200:
                    return []
                payload = resp.json()
        except Exception as exc:
            logger.debug(f"[remotive.com] fetch skipped: {exc}")
            return []

        for job in (payload.get("jobs") or [])[:60]:
            title = str(job.get("title") or "").strip()
            company = sanitize_company_name(job.get("company_name"), fallback="Remotive Employer")
            req_loc = str(job.get("candidate_required_location") or "Worldwide").strip()
            raw_desc = _strip_html(str(job.get("description") or ""))
            sal_raw = str(job.get("salary") or "").strip()
            if not title:
                continue
            if not _matches_domain(title, raw_desc, domain_keywords):
                continue

            combined_desc = f"Location: {req_loc} | Contract: {job.get('job_type') or 'Remote'} | {sal_raw}\n{raw_desc}".strip()
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=combined_desc,
                location_text=req_loc,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

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
                "status": "DISCOVERED",
            })

        return results


class HimalayasScraper:
    """
    Live Global Remote B2B Scraper using Himalayas' public JSON API
    (https://himalayas.app/jobs/api?limit=50), preserving explicit salary & country restrictions.
    """

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

        results: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    self.API_URL,
                    headers={"User-Agent": "TalentFlowAI/2.0 (Remote Job Discovery)"},
                )
                if resp.status_code != 200:
                    return []
                payload = resp.json()
        except Exception as exc:
            logger.debug(f"[himalayas.app] fetch skipped: {exc}")
            return []

        for idx, job in enumerate((payload.get("jobs") or [])[:50]):
            title = str(job.get("title") or "").strip()
            company = sanitize_company_name(job.get("companyName"), fallback="Himalayas Employer")
            locs = job.get("locationRestrictions") or []
            loc_str = ", ".join(str(x) for x in locs if x) if isinstance(locs, list) and locs else "Worldwide"
            tzs = job.get("timezoneRestrictions") or []
            tz_str = f"Timezones: {', '.join(str(t) for t in tzs)}" if isinstance(tzs, list) and tzs else ""
            raw_desc = _strip_html(str(job.get("description") or job.get("excerpt") or ""))
            if not title:
                continue
            if not _matches_domain(title, raw_desc, domain_keywords):
                continue

            sal_prefix = ""
            min_s = job.get("minSalary")
            max_s = job.get("maxSalary")
            cur = str(job.get("currency") or "USD").strip().upper()
            if min_s or max_s:
                lo = min_s or max_s
                hi = max_s or min_s
                sal_prefix = f"Salary: {lo}-{hi} {cur}. "

            combined_desc = f"{sal_prefix}Allowed Locations: {loc_str}. {tz_str}\n{raw_desc}".strip()
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=combined_desc,
                location_text=loc_str,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

            url = str(job.get("guid") or job.get("applicationLink") or "").split("?")[0].strip()
            if not url:
                continue

            results.append({
                "portal": self.portal_name,
                "external_id": f"himalayas-{job.get('companySlug') or 'co'}-{idx}-{hash(url) & 0xFFFFF}",
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
                "status": "DISCOVERED",
            })

        return results


class RemoteOkScraper:
    """
    Live Global Remote & Contractor Scraper using RemoteOK's public JSON API
    (https://remoteok.com/api).
    """

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

        results: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    self.API_URL,
                    headers={"User-Agent": "TalentFlowAI/2.0 (Remote Job Discovery)"},
                )
                if resp.status_code != 200:
                    return []
                items = resp.json()
        except Exception as exc:
            logger.debug(f"[remoteok.com] fetch skipped: {exc}")
            return []

        if not isinstance(items, list):
            return []

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

            sal_min = job.get("salary_min") or 0
            sal_max = job.get("salary_max") or 0
            sal_str = f"Compensation: ${int(sal_min):,} - ${int(sal_max):,} USD. " if sal_min and sal_max else ""
            combined_desc = f"{sal_str}Location: {req_loc}. Tags: {tags}.\n{raw_desc}".strip()

            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=combined_desc,
                location_text=req_loc,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue

            url = str(job.get("url") or job.get("apply_url") or "").strip()
            if url.startswith("/"):
                url = f"https://remoteok.com{url}"
            if not url:
                continue

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
                "status": "DISCOVERED",
            })

        return results


remotive_scraper = RemotiveScraper()
himalayas_scraper = HimalayasScraper()
remoteok_scraper = RemoteOkScraper()
