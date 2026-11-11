import asyncio
import hashlib
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate

logger = logging.getLogger(__name__)


class JustJoinScraper(BasePortalScraper):
    """
    Live EU / Remote Tech Scraper for JustJoin.it.
    Parses remote testing/tech job offers from SSR HTML and verifies each offer's
    full detail page to filter out Polish-only / on-site-only roles while keeping
    genuine English-speaking Remote B2B opportunities.
    """

    portal_name = "justjoin.it"
    market = "GLOBAL_REMOTE"
    SEARCH_URL = "https://justjoin.it/job-offers/all-locations/testing?workplace=remote"

    def parse_html_listings(self, html: str) -> List[Dict[str, Any]]:
        soup = self.make_soup(html)
        results: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        # Extract Next.js escaped metadata map by slug when present
        slug_meta: Dict[str, Dict[str, str]] = {}
        try:
            unescaped = html.replace('\\"', '"')
            for m in re.finditer(
                r'"slug"\s*:\s*"([^"]+)"[^}]{0,600}?"companyName"\s*:\s*"([^"]+)"',
                unescaped,
            ):
                slug, comp = m.group(1), m.group(2)
                slug_meta[slug] = {"company": comp}
        except Exception:
            pass

        offers = soup.select("a[href*='/job-offer/']")
        for idx, a_tag in enumerate(offers):
            href = str(a_tag.get("href") or "").strip()
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://justjoin.it{href}"
            full_url = full_url.split("?")[0]
            if full_url in seen_urls:
                continue

            title = a_tag.get_text(" ", strip=True)
            # JustJoin renders an empty image overlay anchor followed by the titled anchor
            if not title or len(title) < 3:
                continue
            seen_urls.add(full_url)

            slug = full_url.rstrip("/").split("/")[-1]
            ext_id = f"justjoin-{hashlib.md5(slug.encode('utf-8')).hexdigest()[:12]}"

            company = slug_meta.get(slug, {}).get("company", "")
            if not company and slug:
                # Infer clean company prefix from slug when Next.js chunk didn't expose it inline
                slug_head = slug.split("-")[0]
                company = slug_head.capitalize() if len(slug_head) > 1 else "JustJoin Partner"

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company or "JustJoin Partner",
                "url": full_url,
                "market": self.market,
                "is_remote": True,
                "channel": "WEB_FORM",
                "detected_languages": ["English"],
                "language_requirements": ["English"],
                "description_raw": f"{title} at {company} (JustJoin.it Remote)",
                "status": "DISCOVERED",
            })

        return results

    def _fallback_curated_listings(self) -> List[Dict[str, Any]]:
        return []

    async def _enrich_and_verify_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fetches full offer page, validates remote/English requirements, and rejects Polish-only descriptions."""
        html = await self.fetch_html(item["url"], timeout=8.0)
        if not html:
            return None

        soup = self.make_soup(html)
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        page_text = soup.get_text(" ", strip=True)
        if len(page_text) < 200:
            return None

        # Trim navigation chrome before "Job description" if present
        jd_idx = page_text.lower().find("job description")
        body_text = page_text[jd_idx:jd_idx + 5000] if jd_idx != -1 else page_text[:5000]

        # Extract authentic company name from page header / h2 if slug fallback was short
        h1_el = soup.find("h1")
        if h1_el and h1_el.parent:
            parent_links = [
                a.get_text(" ", strip=True)
                for a in soup.select("a[href*='/companies/'], a[href*='/job-offers/']")
                if a.get_text(strip=True) and a.get_text(strip=True) != item["title"]
            ]
            for cand in parent_links:
                if 2 <= len(cand) <= 50 and cand.lower() not in ("all offers", "testing", "remote"):
                    item["company"] = cand
                    break

        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=body_text,
            location_text="Remote EU / B2B",
            portal=self.portal_name,
        )
        item["is_remote"] = is_remote
        item["status"] = status
        item["filter_out_reason"] = filter_reason or None
        item["match_rationale"] = filter_reason
        item["detected_languages"] = langs
        item["language_requirements"] = langs
        item["description_raw"] = body_text
        return item

    async def scrape(
        self,
        allow_network: bool = True,
        search_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []

        target_url = search_url or self.SEARCH_URL
        urls = [target_url]
        if "experience-level=" not in target_url:
            urls.append(f"{target_url}&experience-level=junior,mid")

        pages = await asyncio.gather(*(self.fetch_html(u) for u in urls), return_exceptions=True)
        candidates: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for html in pages:
            if isinstance(html, str) and html:
                for item in self.parse_html_listings(html):
                    if item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        candidates.append(item)

        if not candidates:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_and_verify_item(c) for c in candidates[:20]),
            return_exceptions=True,
        )
        return [x for x in enriched if isinstance(x, dict)]


justjoin_scraper = JustJoinScraper()
