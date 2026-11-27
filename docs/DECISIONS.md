# TalentFlow AI — Engineering & Product Decision Log

This log records every feature removal, simplification, and architectural trade-off made during the Phase 0–4 refactor on `agent/audit-search-ai-refactor`.

---

## DEC-001: Remove Server-Side Playwright Form Auto-Staging
- **Status:** Accepted & Implemented
- **Removed:** `backend/app/services/playwright_service.py`, `backend/app/routers/stage.py`, `ENABLE_PLAYWRIGHT`, `playwright` in `backend/requirements.txt`, Chromium install in `.github/workflows/ci.yml`, `StageApplicationRequest`/`StageApplicationResponse`, and `stageApplication()` in `frontend/src/services/api.ts`.
- **Why:**
  1. Authenticated portals (HeadHunter.ge, LinkedIn, Workday, etc.) require the user's live logged-in browser session; a server-side headless browser cannot authenticate safely or reliably without credential-handling risks.
  2. Playwright + Chromium was the heaviest runtime dependency and highest complexity surface in the backend.
  3. The Chrome Extension (`extension/`, Manifest V3) already handles authenticated in-session DOM extraction, editable answer pre-fill, and human-in-the-loop review cleanly.
- **Replacement:** Direct portal links, prepared email/Gmail draft packages with `.docx`/`.pdf` CV attachments, and the Chrome Extension copilot.

---

## DEC-002: Remove Server-Side LinkedIn Scraping (Extension-Only Policy)
- **Status:** Accepted & Implemented
- **Removed:** `backend/app/services/scrapers/linkedin_scraper.py`, `ENABLE_LINKEDIN_PUBLIC_SCRAPE`, `linkedin.com` from `ScraperOrchestrator.SCRAPER_MAP` & `DEFAULT_PORTALS`, and `linkedin_urls` from `query_builder.py`.
- **Why:** LinkedIn's Terms of Service prohibit automated server-side scraping and guest endpoints are brittle/rate-limited. Supporting LinkedIn exclusively inside the user's own authenticated browser via `extension/` respects user-driven browsing and removes a high-risk maintenance burden.

### Per-Portal Scraping Terms & Operational Risk Matrix
| Portal | Mode | Notes & Risk |
| --- | --- | --- |
| `jobs.ge`, `hr.ge`, `hr.gov.ge` | Server-side public HTML | Georgian public job boards; bounded concurrency, timeouts, and source health tracking. Respect site load limits. |
| `headhunter.ge` | Server-side public HTML | Public vacancy listings only; authenticated applications happen in user's browser/extension. |
| `remotive.com`, `himalayas.app`, `remoteok.com` | Server-side public JSON APIs | Public feed APIs with standard attribution and timeouts. |
| `greenhouse.io`, `lever.co` | Server-side public ATS board APIs | Official public job-board JSON endpoints. |
| `djinni.co`, `dou.ua`, `justjoin.it` | Server-side public HTML/JSON | Regional remote boards; monitored via `get_source_health()` for zero-result/blocking regressions. |
| `linkedin.com` | **Chrome Extension only** | No server-side scraping (`DEC-002`). User opens listings directly in Chrome. |

---

## DEC-003: Keep Georgia B2B Tax Hub Behind Feature Flag (`ENABLE_B2B_HUB`)
- **Status:** Accepted & Implemented
- **Changes:** Extracted tax/FX/timezone business logic from `routers/b2b.py` into `services/b2b_tax_service.py` with `GEO_TAX_CONFIG` (citing Georgian Tax Code Article 90, effective `2026-01-01`, and explicit "not legal or tax advice" disclaimer), removed duplicate sync NBG FX fetcher, and gated router mounting behind `ENABLE_B2B_HUB` (default `true` for the core Georgian remote-worker audience).

---

## DEC-004: Collapse Duplicate Endpoints (`/jobs/scrape` and `/cv-variants`)
- **Status:** Accepted & Implemented
- **Removed:** Synchronous `POST /api/jobs/scrape` (plus `triggerMultiPortalScrape` in `frontend/src/services/api.ts`) and legacy `GET /api/cv-variants`.
- **Replacement:**
  - Single durable asynchronous scrape API: `POST /api/jobs/scrape/async` + `GET /api/jobs/scrape/status/{task_id}` (with stale-task recovery, heartbeats, and per-user deduplication).
  - Canonical CV versioning endpoints under `/api/cv-versions` (supporting blank/master/tailored creation, duplication, comparison, ATS checks, and persisted cover/motivational letters).

---

## DEC-005: Soft Delete vs. Hard Purge on `DELETE /api/applications/{id}`
- **Status:** Accepted & Implemented (Phase 1)
- **Decision:** Keep the `hard: bool = False` query parameter and implement both behaviors explicitly:
  - `hard=false` (default): Marks `is_deleted=True`, sets `submission_status="DELETED"`, hides record from list/get queries, and records a `soft_deleted` `ApplicationEvent` audit entry.
  - `hard=true`: Permanently purges the owned `ApplicationTracker`, linked `ApplicationRecord`, `ApplicationEvent`, and `InterviewRound` rows inside a single transaction after strict ownership verification.

---

## DEC-006: Evidence-Backed Claims Only in Documentation
- **Status:** Accepted & Implemented
- **Decision:** Trimmed `README.md` to remove unverified marketing language ("Top-1%") and report only measured capabilities backed by automated tests and the offline 30-case golden evaluation + zero-fabrication groundedness harness (`backend/evals/eval_runner.py`).
