import asyncio
import logging
from typing import Dict, Any, List, Optional
from .base_scraper import (
    BasePortalScraper,
    evaluate_remote_and_language_gate,
    matches_domain_keywords,
    parse_portal_published_at,
)

logger = logging.getLogger(__name__)


def _sort_newest(items: List[Dict[str, Any]], cap: int = 30) -> List[Dict[str, Any]]:
    items.sort(key=lambda x: x["published_at"].timestamp() if x.get("published_at") else 0.0, reverse=True)
    return items[:cap]


class GreenhouseScraper(BasePortalScraper):
    """
    Scrapes public Greenhouse ATS job boards concurrently across ALL departments (Engineering, QA,
    Finance, Marketing, Sales, Operations, Legal, HR, Support) via official JSON API.
    """

    portal_name = "greenhouse.io"
    DEFAULT_BOARDS = ["stripe", "cloudflare", "gitlab", "canonical", "datadog", "grafanalabs", "airbnb", "coinbase"]

    async def _scrape_board(
        self,
        board: str,
        kw_lower: List[str],
        candidate_languages: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        data = await self.fetch_json(api_url, timeout=9.0)
        if not isinstance(data, dict):
            return []
        items: List[Dict[str, Any]] = []
        for job in (data.get("jobs") or []):
            title = str(job.get("title") or "").strip()
            if not title:
                continue
            loc_name = str((job.get("location") or {}).get("name") or "Remote").strip()
            depts = " ".join(str(d.get("name") or "") for d in (job.get("departments") or []) if isinstance(d, dict))
            content = str(job.get("content") or "").strip()
            abs_url = str(job.get("absolute_url") or "").strip()
            if kw_lower and not matches_domain_keywords(f"{title} {depts}", kw_lower[:16]):
                continue
            desc_blob = content or f"{title} | Department: {depts or 'General'} | Location: {loc_name} ({board.capitalize()})"
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc_blob,
                location_text=loc_name,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue
            pub_dt, pub_str = parse_portal_published_at(job.get("updated_at") or job.get("first_published"))
            items.append({
                "portal": self.portal_name,
                "external_id": f"gh-{board}-{job.get('id', '')}",
                "title": title,
                "company": board.capitalize(),
                "url": abs_url or api_url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": loc_name,
                "description_raw": desc_blob[:4000],
                "detected_languages": langs,
                "posting_date": pub_str,
                "published_at": pub_dt,
                "status": "DISCOVERED",
            })
        return _sort_newest(items, cap=10)

    async def scrape(
        self,
        allow_network: bool = True,
        boards: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_boards = (boards or self.DEFAULT_BOARDS)[:8]
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        batches = await asyncio.gather(
            *(self._scrape_board(b, kw_lower, candidate_languages) for b in target_boards),
            return_exceptions=True,
        )
        merged = [item for batch in batches if isinstance(batch, list) for item in batch]
        return _sort_newest(merged, cap=30)


class LeverScraper(BasePortalScraper):
    """
    Scrapes public Lever ATS job postings concurrently across ALL departments via official JSON API.
    """

    portal_name = "lever.co"
    DEFAULT_COMPANIES = ["palantir", "zoox", "spotify", "ro", "binance"]

    async def _scrape_company(
        self,
        comp: str,
        kw_lower: List[str],
        candidate_languages: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        api_url = f"https://api.lever.co/v0/postings/{comp}?mode=json"
        postings = await self.fetch_json(api_url, timeout=9.0)
        if not isinstance(postings, list):
            return []
        items: List[Dict[str, Any]] = []
        for post in postings:
            title = str(post.get("text") or "").strip()
            if not title:
                continue
            cats = post.get("categories") or {}
            dept_team = f"{cats.get('department') or ''} {cats.get('team') or ''}".strip()
            loc_name = str(cats.get("location") or post.get("workplaceType") or "Remote").strip()
            desc = str(post.get("descriptionPlain") or post.get("description") or "").strip()
            hosted_url = str(post.get("hostedUrl") or "").strip()
            if kw_lower and not matches_domain_keywords(f"{title} {dept_team}", kw_lower[:16]):
                continue
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc or f"{title} | {dept_team} | {loc_name}",
                location_text=loc_name,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue
            pub_dt, pub_str = parse_portal_published_at(post.get("createdAt"))
            items.append({
                "portal": self.portal_name,
                "external_id": f"lever-{comp}-{post.get('id', '')}",
                "title": title,
                "company": comp.capitalize(),
                "url": hosted_url or api_url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": loc_name,
                "description_raw": (desc or f"{title} at {comp.capitalize()} ({dept_team})")[:4000],
                "detected_languages": langs,
                "posting_date": pub_str,
                "published_at": pub_dt,
                "status": "DISCOVERED",
            })
        return _sort_newest(items, cap=10)

    async def scrape(
        self,
        allow_network: bool = True,
        companies: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_companies = (companies or self.DEFAULT_COMPANIES)[:6]
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        batches = await asyncio.gather(
            *(self._scrape_company(c, kw_lower, candidate_languages) for c in target_companies),
            return_exceptions=True,
        )
        merged = [item for batch in batches if isinstance(batch, list) for item in batch]
        return _sort_newest(merged, cap=30)


greenhouse_scraper = GreenhouseScraper()
lever_scraper = LeverScraper()
