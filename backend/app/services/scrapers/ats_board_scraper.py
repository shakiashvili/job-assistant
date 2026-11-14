import logging
from typing import Dict, Any, List, Optional
import httpx
from .base_scraper import evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class GreenhouseScraper:
    """
    Scrapes public Greenhouse ATS job boards via their official JSON API
    (https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true).
    """

    DEFAULT_BOARDS = ["gitlab", "canonical", "automattic", "grafanalabs", "wikimedia"]

    async def scrape(
        self,
        allow_network: bool = True,
        boards: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        target_boards = boards or self.DEFAULT_BOARDS
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        results: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for board in target_boards[:5]:
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
                try:
                    resp = await client.get(api_url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for job in (data.get("jobs") or [])[:25]:
                        title = str(job.get("title") or "").strip()
                        loc_name = str((job.get("location") or {}).get("name") or "Remote").strip()
                        content = str(job.get("content") or "").strip()
                        abs_url = str(job.get("absolute_url") or "").strip()
                        ext_id = f"gh-{board}-{job.get('id', '')}"

                        if kw_lower and not any(k in title.lower() or k in content.lower() for k in kw_lower[:10]):
                            continue

                        is_rem, gate_status, gate_reason, langs = evaluate_remote_and_language_gate(
                            title=title,
                            description=content,
                            location_text=loc_name,
                            portal="greenhouse.io",
                            candidate_languages=candidate_languages,
                        )
                        if gate_status == "FILTERED_OUT":
                            continue

                        results.append({
                            "portal": "greenhouse.io",
                            "external_id": ext_id,
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
                except Exception as e:
                    logger.debug(f"Greenhouse board {board} fetch skipped: {e}")

        return results


class LeverScraper:
    """
    Scrapes public Lever ATS job postings via their official JSON API
    (https://api.lever.co/v0/postings/{company}?mode=json).
    """

    DEFAULT_COMPANIES = ["netflix", "palantir", "koho", "welocalize"]

    async def scrape(
        self,
        allow_network: bool = True,
        companies: Optional[List[str]] = None,
        domain_keywords: Optional[List[str]] = None,
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        target_companies = companies or self.DEFAULT_COMPANIES
        kw_lower = [k.lower() for k in (domain_keywords or []) if k]
        results: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for comp in target_companies[:5]:
                api_url = f"https://api.lever.co/v0/postings/{comp}?mode=json"
                try:
                    resp = await client.get(api_url)
                    if resp.status_code != 200:
                        continue
                    postings = resp.json()
                    if not isinstance(postings, list):
                        continue
                    for post in postings[:25]:
                        title = str(post.get("text") or "").strip()
                        cats = post.get("categories") or {}
                        loc_name = str(cats.get("location") or post.get("workplaceType") or "Remote").strip()
                        desc = str(post.get("descriptionPlain") or post.get("description") or "").strip()
                        hosted_url = str(post.get("hostedUrl") or "").strip()
                        ext_id = f"lever-{comp}-{post.get('id', '')}"

                        if kw_lower and not any(k in title.lower() or k in desc.lower() for k in kw_lower[:10]):
                            continue

                        is_rem, gate_status, gate_reason, langs = evaluate_remote_and_language_gate(
                            title=title,
                            description=desc,
                            location_text=loc_name,
                            portal="lever.co",
                            candidate_languages=candidate_languages,
                        )
                        if gate_status == "FILTERED_OUT":
                            continue

                        results.append({
                            "portal": "lever.co",
                            "external_id": ext_id,
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
                except Exception as e:
                    logger.debug(f"Lever board {comp} fetch skipped: {e}")

        return results


greenhouse_scraper = GreenhouseScraper()
lever_scraper = LeverScraper()
