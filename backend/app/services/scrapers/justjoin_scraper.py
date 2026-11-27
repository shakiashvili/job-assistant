import hashlib
import logging
import re
from typing import Dict, Any, List, Optional
from .base_scraper import BasePortalScraper, evaluate_remote_and_language_gate, parse_portal_published_at

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

        # Extract Next.js App Router RSC offer metadata (companyName, publishedAt, workplaceType) by slug
        slug_meta: Dict[str, Dict[str, Any]] = {}
        try:
            unescaped = html.replace('\\"', '"')
            for m in re.finditer(r'"slug"\s*:\s*"([^"]+)"', unescaped):
                slug = m.group(1)
                if slug in slug_meta:
                    continue
                window = unescaped[m.start():m.start() + 1800]
                comp_m = re.search(r'"companyName"\s*:\s*"([^"]+)"', window)
                pub_m = re.search(r'"publishedAt"\s*:\s*"([^"]+)"', window)
                wp_m = re.search(r'"workplaceType"\s*:\s*"([^"]+)"', window)
                skills_m = re.search(r'"requiredSkills"\s*:\s*\[([^\]]*)\]', window)
                req_skills = re.findall(r'"([^"]+)"', skills_m.group(1)) if skills_m else []
                slug_meta[slug] = {
                    "company": comp_m.group(1) if comp_m else "",
                    "published_at": pub_m.group(1) if pub_m else None,
                    "workplace": (wp_m.group(1) or "").lower() if wp_m else "",
                    "skills": req_skills[:10],
                }
        except Exception as meta_err:
            logger.debug("[justjoin.it] Could not parse embedded slug metadata: %s", meta_err)

        offers = soup.select("a[href*='/job-offer/']")
        for _idx, a_tag in enumerate(offers):
            href = str(a_tag.get("href") or "").strip()
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://justjoin.it{href}"
            full_url = full_url.split("?")[0]
            if full_url in seen_urls:
                continue

            title = a_tag.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue
            seen_urls.add(full_url)

            slug = full_url.rstrip("/").split("/")[-1]
            ext_id = f"justjoin-{hashlib.md5(slug.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]}"
            meta = slug_meta.get(slug, {})

            company = meta.get("company", "")
            if not company and slug:
                slug_head = slug.split("-")[0]
                company = slug_head.capitalize() if len(slug_head) > 1 else "JustJoin Partner"

            pub_dt, pub_str = parse_portal_published_at(meta.get("published_at"))

            card_blob = a_tag.get_text(" ", strip=True)
            parent_box = a_tag.find_parent("div")
            if parent_box:
                card_blob = f"{card_blob} {parent_box.get_text(' ', strip=True)}"

            wp_meta = meta.get("workplace", "")
            is_card_hybrid = wp_meta == "partly_remote" or bool(re.search(r"\b(hybrid|hybryd|partly[\s-]remote|częściowo)\b", card_blob, re.IGNORECASE))
            is_card_onsite = wp_meta == "office" or bool(re.search(r"\b(office|stacjonarn|w\s+biurze)\b", card_blob, re.IGNORECASE))
            initial_status = "FILTERED_OUT" if (is_card_hybrid or is_card_onsite) else "DISCOVERED"
            initial_filter_reason = (
                "Location/Work-Mode Gate: Foreign vacancy is Hybrid (requires physical office attendance abroad; only 100% Remote positions accepted)"
                if is_card_hybrid
                else (
                    "Location/Work-Mode Gate: Foreign vacancy is On-site (requires physical presence abroad; only 100% Remote positions accepted)"
                    if is_card_onsite
                    else None
                )
            )
            skills_txt = f" | Skills: {', '.join(meta.get('skills') or [])}" if meta.get("skills") else ""

            results.append({
                "portal": self.portal_name,
                "external_id": ext_id,
                "title": title,
                "company": company or "JustJoin Partner",
                "url": full_url,
                "market": self.market,
                "is_remote": not (is_card_hybrid or is_card_onsite),
                "channel": "WEB_FORM",
                "detected_languages": ["English"],
                "language_requirements": ["English"],
                "published_at": pub_dt,
                "posting_date": pub_str,
                "description_raw": f"{title} at {company} (JustJoin.it Remote){skills_txt}",
                "status": initial_status,
                "filter_out_reason": initial_filter_reason,
            })

        return results

    async def _enrich_and_verify_item(
        self,
        item: Dict[str, Any],
        candidate_languages: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetches full offer page, validates remote/language requirements (unlocking Polish if in skills.md)."""
        html = await self.fetch_html(item["url"], timeout=7.0)
        if not html:
            return item

        soup = self.make_soup(html)
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        page_text = soup.get_text(" ", strip=True)
        if len(page_text) < 200:
            return item

        loc_badges = [
            t.strip() for t in soup.find_all(string=re.compile(r"\b(hybrid|hybryd|stacjonarn|remote|zdaln|office|biur|b2b|contract)\b", re.I))
            if len(t.strip()) < 50
        ]
        location_meta = " | ".join(dict.fromkeys(loc_badges)) if loc_badges else "Remote EU / B2B"
        body_text = page_text[:8000]

        h1_el = soup.find("h1")
        if h1_el and (not item.get("company") or item.get("company") == "JustJoin Partner"):
            parent_links = [
                a.get_text(" ", strip=True)
                for a in soup.select("a[href*='/companies/']")
                if a.get_text(strip=True) and a.get_text(strip=True) != item["title"]
            ]
            for cand in parent_links:
                if 2 <= len(cand) <= 60:
                    item["company"] = cand
                    break

        is_remote, status, filter_reason, langs = evaluate_remote_and_language_gate(
            title=item["title"],
            description=body_text,
            location_text=location_meta,
            portal=self.portal_name,
            candidate_languages=candidate_languages,
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
        candidate_languages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not allow_network:
            return []
        target_url = search_url or self.SEARCH_URL
        urls = [target_url]
        if "experience-level=" not in target_url:
            urls.append(f"{target_url}&experience-level=junior,mid")
        return await self.scrape_and_enrich_urls(
            urls,
            self.parse_html_listings,
            lambda c: self._enrich_and_verify_item(c, candidate_languages=candidate_languages),
            limit=18,
            dedupe_key="url",
            page_timeout=10.0,
            sort_newest_first=True,
        )


justjoin_scraper = JustJoinScraper()
