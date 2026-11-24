import asyncio
import logging
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class GreenhouseScraper(BasePortalScraper):
    """
    Scrapes public Greenhouse ATS job boards concurrently via their official JSON API
    (https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true).
    """

    portal_name = "greenhouse.io"
    DEFAULT_BOARDS = ["gitlab", "canonical", "automattic", "grafanalabs", "wikimedia"]

    async def _scrape_board(
        self,
        board: str,
        kw_lower: List[str],
        candidate_languages: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        data = await self.fetch_json(api_url, timeout=8.0)
        if not isinstance(data, dict):
            return []
        items: List[Dict[str, Any]] = []
        for job in (data.get("jobs") or [])[:25]:
            title = str(job.get("title") or "").strip()
            loc_name = str((job.get("location") or {}).get("name") or "Remote").strip()
            content = str(job.get("content") or "").strip()
            abs_url = str(job.get("absolute_url") or "").strip()
            if kw_lower and not any(k in title.lower() or k in content.lower() for k in kw_lower[:10]):
                continue
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=content,
                location_text=loc_name,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue
            items.append({
                "portal": self.portal_name,
                "external_id": f"gh-{board}-{job.get('id', '')}",
                "title": title,
                "company": board.capitalize(),
                "url": abs_url or api_url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": loc_name,
                "description_raw": content[:4000],
                "detected_languages": langs,
                "status": "DISCOVERED",
            })
        return items

    async def scrape(
        self,
        allow_network: bool = True,
        boards: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_boards = (boards or self.DEFAULT_BOARDS)[:5]
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        batches = await asyncio.gather(
            *(self._scrape_board(b, kw_lower, candidate_languages) for b in target_boards),
            return_exceptions=True,
        )
        return [item for batch in batches if isinstance(batch, list) for item in batch]


class LeverScraper(BasePortalScraper):
    """
    Scrapes public Lever ATS job postings concurrently via their official JSON API
    (https://api.lever.co/v0/postings/{company}?mode=json).
    """

    portal_name = "lever.co"
    DEFAULT_COMPANIES = ["netflix", "palantir", "koho", "welocalize"]

    async def _scrape_company(
        self,
        comp: str,
        kw_lower: List[str],
        candidate_languages: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        api_url = f"https://api.lever.co/v0/postings/{comp}?mode=json"
        postings = await self.fetch_json(api_url, timeout=8.0)
        if not isinstance(postings, list):
            return []
        items: List[Dict[str, Any]] = []
        for post in postings[:25]:
            title = str(post.get("text") or "").strip()
            cats = post.get("categories") or {}
            loc_name = str(cats.get("location") or post.get("workplaceType") or "Remote").strip()
            desc = str(post.get("descriptionPlain") or post.get("description") or "").strip()
            hosted_url = str(post.get("hostedUrl") or "").strip()
            if kw_lower and not any(k in title.lower() or k in desc.lower() for k in kw_lower[:10]):
                continue
            is_rem, gate_status, _, langs = evaluate_remote_and_language_gate(
                title=title,
                description=desc,
                location_text=loc_name,
                portal=self.portal_name,
                candidate_languages=candidate_languages,
            )
            if gate_status == "FILTERED_OUT":
                continue
            items.append({
                "portal": self.portal_name,
                "external_id": f"lever-{comp}-{post.get('id', '')}",
                "title": title,
                "company": comp.capitalize(),
                "url": hosted_url or api_url,
                "market": "GLOBAL_REMOTE",
                "is_remote": is_rem,
                "location": loc_name,
                "description_raw": desc[:4000],
                "detected_languages": langs,
                "status": "DISCOVERED",
            })
        return items

    async def scrape(
        self,
        allow_network: bool = True,
        companies: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_companies = (companies or self.DEFAULT_COMPANIES)[:5]
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        batches = await asyncio.gather(
            *(self._scrape_company(c, kw_lower, candidate_languages) for c in target_companies),
            return_exceptions=True,
        )
        return [item for batch in batches if isinstance(batch, list) for item in batch]


greenhouse_scraper = GreenhouseScraper()
lever_scraper = LeverScraper()
