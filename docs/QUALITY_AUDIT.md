# TalentFlow AI — Full Repository Engineering & Quality Audit

**Branch:** `agent/full-quality-and-cv-trust`  
**Base Commit:** `main` (`e0dd609`)  
**Repository:** `shakiashvili/job-assistant`  
**Tracked Files Reviewed:** 147 repository-owned files across backend, frontend, Chrome extension, migrations, tests, CI/CD, and docs (plus runtime/fixture artifacts).

---

## 1. Executive Summary & Baseline Measurements

### Baseline Verification (Pre-Fix Snapshot)
- **Backend Functional Test Suite** (`python -m pytest tests -q --tb=short` from `backend/`): `85 passed in 33.19s` (note: several tests explicitly asserted synthetic defaults such as `"1 week after offer"`, `38000` salary, or automatic `ApplicationRecord` creation during ingestion).
- **Non-Functional Security Suite** (`python -m pytest tests/non_functional/test_security.py -v --tb=short`): `7 passed in 6.79s` (2 deprecation warnings).
- **Frontend Production Build** (`npm run build` in `frontend/`): Exit `0`, `✓ 1587 modules transformed` in `4.59s`.
- **Georgian Typography Check:** `C:\Windows\Fonts\sylfaen.ttf` (`260,108` bytes) is available on Windows hosts, while `assets/fonts/` does not exist in the repository and Linux CI / `Dockerfile` do not install Georgian Unicode TTF fonts (`fonts-noto-core` / `fonts-dejavu-core`).

### Core Architectural Strengths Already Present
- Solid FastAPI + SQLModel modular separation (`routers/`, `services/`, `db/`, `schemas/`).
- Fernet column encryption (`EncryptedString`, `EncryptedText`, `EncryptedJSON`) paired with HMAC/SHA-256 `email_hash` blind indexing and bcrypt password hashing.
- Strong SSRF URL validator (`link_validator.py`), security response headers, HTML CV Content-Security-Policy, HTTP-only cookie + bearer JWT auth with refresh rotation, and rate-limited OTP verification.
- Genuine multi-portal scrapers (`jobs.ge`, `hr.ge`, `hr.gov.ge`, `djinni.co`, `dou.ua`, `justjoin.it`, `linkedin`, `remotive.com`, `himalayas.app`, `remoteok.com`, Greenhouse/Lever).

### Critical Systemic Defects Discovered
The audit revealed four interlocking architectural and trust failures across the stack:
1. **Encrypted Column Query & Cross-User Isolation Bugs:** Lookup queries comparing plaintext emails directly against Fernet-encrypted `User.email` columns silently fail, combined with un-scoped `ground_truth_store.get_data()` calls and cross-user profile fallbacks during scraping.
2. **Pervasive Mock / Fabricated Candidate Facts in Live Workflows:** Hardcoded `1.5` years experience (`max_allowed_years <= 2.0`), `"1 week after offer"`, `€38,000` salary, unverified `"Yes, fully authorized..."` legal authorizations, assumed `["English", "Georgian"]` languages, and `"qa_tech"` / `"Manual QA, REST API, Test Design"` defaults permeate backend services, frontend views, and the extension popup.
3. **Corrupted Application Lifecycle State:** `scraper_orchestrator.py` fabricates full `ApplicationRecord` entries during automated vacancy ingestion—stamping bogus `applied_at`, fake `cv_pdf_path`, fake `cover_letter`, and `"1 week after offer"` even though the user never applied.
4. **Deprecated Gemini 2.5 Stack & Weak Prompt Isolation:** Production config and `gemini_service.py` target retired/deprecated `gemini-2.5-flash` without SDK request timeouts, lack randomized XML nonce prompt delimiters around untrusted job descriptions, share cache entries without user/profile isolation where needed, and conflate Cover Letters vs Motivational Letters.

---

## 2. Prioritized Defect & Improvement Register

### Critical Priority (P0)
| ID | Area | Defect / Risk | Root Cause & Location | Fix Plan |
|---|---|---|---|---|
| **C-01** | Security / Data Isolation | Direct SQL equality against Fernet-encrypted `User.email` (`WHERE User.email == ...`) always misses in production and test DBs. | `backend/app/db/profile_repository.py:218`, `backend/app/services/profile_service.py:543` | Replace direct `User.email ==` filters with `get_user_by_email(session, email)` using `email_hash` blind index. |
| **C-02** | Security / Multi-Tenancy | Cross-user profile leakage in form answers & scraper ingestion. | `answer_service.py:63,70` calls `ground_truth_store.get_data()` without `user_id`/`owner_email`; `scraper_orchestrator.py:353-358` falls back to any arbitrary user's `CandidateProfile`. | Require explicit `user_id`/`owner_email` scoping in `AnswerService`; eliminate cross-user profile fallback in `ScraperOrchestrator`. |
| **C-03** | Data Integrity / Lifecycle | Scraping automatically manufactures fake `ApplicationRecord` rows with `applied_at=now_utc`, synthetic `cv_pdf_path`, fake `cover_letter`, and `"1 week after offer"`. | `backend/app/services/scrapers/scraper_orchestrator.py:577-595`; `tracker_repository.py` non-null `applied_at` | Remove automatic `ApplicationRecord` creation from `ingest_scraped_jobs()`; make `ApplicationRecord.applied_at` nullable (`None` until explicitly applied/submitted) with Alembic migration. |
| **C-04** | AI Trust / Zero Fabrication | Unverified fabrication of `1.5` yrs experience, `"1 week after offer"`, `€38,000`, `"Yes, fully authorized..."`, `["English", "Georgian"]`, `"qa_tech"`, `"Manual QA, REST API, Test Design"`, `"Senior QA Automation Engineer"`. | `profile_service.py`, `matcher_service.py`, `audit_service.py`, `answer_service.py`, `cv_generator_service.py`, `playwright_service.py`, `portal_detector.py`, `plan_service.py`, `query_builder.py`, `extension.py`, `DiscoveryFeed.tsx`, `AuditPanel.tsx`, `InterviewPrepModal.tsx`, `popup.js` | Introduce explicit `experience_years: Optional[float]`, `experience_status` (`confirmed \| internship_or_project \| unknown`), remove all fabricated legal/notice/salary/language/skill defaults, return empty/needs-confirmation states instead of inventing data. |
| **C-05** | AI Engine / Security | `gemini-2.5-flash` is deprecated/retired; missing SDK `HttpOptions(timeout=...)`; deprecated `temperature` overrides for Gemini 3.x; weak prompt injection framing around scraped HTML/text; `main.py` `/health` hardcodes `"live_gemini_2.5_flash"`. | `backend/app/config.py`, `backend/app/services/gemini_service.py`, `backend/app/main.py:157`, `render.yaml`, `docs/DEPLOYMENT.md` | Upgrade defaults to `gemini-3.6-flash` (quality) & `gemini-3.5-flash-lite` (fast), enforce `HttpOptions(timeout=30000)`, omit deprecated sampling params on 3.x+, wrap untrusted job text in cryptographic per-call `<job_description_{nonce}>` delimiters with `system_instruction`, isolate cache scope by `user_id` where relevant. |
| **C-06** | Security / Production Config | `render.yaml` sets `ENVIRONMENT=production` without `ENCRYPTION_KEY`; `tracker.py:79` falls back invalid IDs to `1` (`int(...) if ... else 1`); `StageModal.tsx:168,381` binds unvalidated `urlInput` to `<a href>`; unsupported `.doc` advertised in UI while backend cannot parse `.doc`. | `render.yaml`, `backend/app/routers/tracker.py:79`, `frontend/src/components/StageModal.tsx`, `CVVariantManager.tsx`, `AuditPanel.tsx`, `ProfileVault.tsx` | Declare `ENCRYPTION_KEY` in `render.yaml`; reject non-numeric tracker IDs with HTTP 400; validate `http://`/`https://` URLs before rendering `<a href>`; restrict UI uploads and parser validation to `.pdf`, `.docx`, `.md`, `.txt`. |

### High Priority (P1)
| ID | Area | Defect / Risk | Root Cause & Location | Fix Plan |
|---|---|---|---|---|
| **H-01** | Data Isolation / Demo Content | `PROFESSION_MD_PRESETS` (fictional personas like "Giorgi Shakiashvili", "Nino Kalandadze") sit inside `profile_repository.py` and can accidentally mask empty real user state or overwrite verified data. | `profile_repository.py`, `routers/ground_truth.py` | Keep sample templates strictly behind explicit opt-in demo endpoints (`load_preset`), never inject automatically into unconfigured real accounts, and block overwriting confirmed non-preset profiles unless explicitly requested. |
| **H-02** | CV & Letter Generation | Cover Letter and Motivational Letter share overlapping heuristic phrasing; Linux/Docker environments lack Georgian TTF font fallback (`fonts-noto-core`); no programmatic anti-hallucination validator runs over generated CV/letters. | `backend/app/services/cv_generator_service.py`, `Dockerfile`, `.github/workflows/ci.yml` | Implement domain-adaptive skill buckets (non-IT profiles never see QA defaults), enforce distinct concise Cover Letter (2–3 paragraphs) vs deeper Motivational Letter (3–4 paragraphs), add verification validator checking zero unverified facts/foreign scripts, bundle/install Noto Georgian + DejaVu fonts in CI & Docker while keeping Word OOXML `Sylfaen` for KA `.docx`. |
| **H-03** | Chrome Extension Least Privilege | `manifest.json` requests `"https://*/*"`, `"http://*/*"` wildcard host permissions despite `docs/EXTENSION.md` claiming `<all_urls>` is avoided. | `extension/manifest.json`, `extension/popup/popup.js` | Narrow `host_permissions` to backend/localhost + `activeTab` / supported job board hosts, move arbitrary ATS domains to `optional_host_permissions` requested explicitly on user action via `chrome.permissions.request()`. |
| **H-04** | Frontend Performance & State | `CVVariantManager.tsx:116-128` eagerly fans out up to `10 x 100 = 1,000` jobs on mount; `triggerCrossOriginDownload` prints `"Downloaded!"` even when falling back or failing; unawaited `navigator.clipboard.writeText`. | `frontend/src/components/CVVariantManager.tsx` | Replace eager 1,000-job fetch with debounced server-side `/api/jobs?search=...&limit=25`; await blob downloads cleanly and display real errors on failure; handle clipboard Promise rejections with fallback feedback. |
| **H-05** | Frontend Correctness & UX | `AuditPanel.tsx` pagination/search handlers drop `b2bOnlyFilter` & `geoEligibleOnlyFilter`; `DiscoveryFeed.tsx` truncates pagination at 5 pages & clamps exp at `1.5`/`2.0`; `StageModal.tsx:310-327` inverts "Pause for Final Review" switch binding (`checked={autoSubmit}`). | `AuditPanel.tsx`, `DiscoveryFeed.tsx`, `StageModal.tsx` | Pass active `b2bOnlyFilter` & `geoEligibleOnlyFilter` through all handlers; build full sliding pagination controls; fix `Pause for Final Review` switch semantics (`checked={!autoSubmit}`). |

### Medium / Low Priority (P2 / P3)
| ID | Area | Defect / Risk | Root Cause & Location | Fix Plan |
|---|---|---|---|---|
| **M-01** | File Parsing Security | `cv_parser_service.py` loads arbitrary `.docx` XML without zip-bomb entry/decompressed size bounds; silently accepts corrupt `.doc` failure. | `backend/app/services/cv_parser_service.py` | Validate DOCX zip archive total uncompressed XML size (`<= 25 MB`) and reject legacy `.doc` with explicit guidance to convert to `.docx` or `.pdf`. |
| **M-02** | Scraper Determinism & Seniority | `remote_b2b_scrapers.py:175` uses Python salted `hash(url)` (non-deterministic across restarts) and misses `http(s)://` validation; `linkedin_scraper.py` hard-filters `Senior`/`Lead`/`3+` roles even for senior users. | `remote_b2b_scrapers.py`, `linkedin_scraper.py` | Switch ID generation to `hashlib.md5` hex digest + URL scheme check; parameterize `linkedin_scraper.py` experience filtering using candidate's `max_allowed_years`. |
| **M-03** | Frontend Accessibility & UX | Browser `alert()` blocking dialogs in `ActionPlanView`, `EmailDispatchModal`, `InterviewPrepModal`, `AdminDashboard`; clickable `<div>` in `ActionPlanView.tsx:206`; missing `aria-label` in `ProfileVault.tsx:623`; low-contrast `text-slate-500` in `DashboardHome.tsx`. | Frontend components | Replace `alert()` with accessible inline/toast status banners; convert clickable `<div>` to semantic `<button>`; add explicit `aria-label`s; raise muted text to `text-slate-300`/`400`. |
| **M-04** | QA / CI & Docs Drift | `ci.yml` misses `ruff`, `tsc --noEmit`, `alembic upgrade head`, and `coverage` checks; triggers omit agent/feature branches; `k6_stress.js` probes `/health` without status/p95 detail; `README.md` and `docs/` contain stale model/architecture claims. | `.github/workflows/ci.yml`, `tests/non_functional/k6_stress.js`, `README.md`, `docs/*` | Add `ruff check`, `npx tsc --noEmit`, `alembic upgrade head` smoke check, pytest coverage; align docs cleanly with audited architecture. |

---

## 3. Complete File-by-File Audit Matrix (147 Tracked Files)

> **Legend:** Review Status is `Reviewed` for every file inspected in full across Sessions 1–2. Status column records disposition across Phases 2–5: planned changes across Sections 3.1–3.7 were implemented and verified via Section 4 checks (new files added: `backend/alembic/versions/c4e8a12f9b30_nullable_applied_at_and_experience_years.py`, `backend/tests/test_quality_and_cv_trust.py`, and this report `docs/QUALITY_AUDIT.md`).

### 3.1 Root, DevOps, CI/CD & Documentation
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `.env.example` | Root environment variable template | Yes | Backend `config.py`, `gemini_service.py` | Still references older model / omits Gemini 3.x fast/quality split guidance | Update in Phase 3 |
| `.github/workflows/ci.yml` | GitHub Actions backend/security/frontend/extension pipeline | Yes | `backend/requirements.txt`, `frontend/`, `extension/`, `tests/` | Missing `ruff`, `tsc --noEmit`, `alembic upgrade head`, Georgian Linux fonts for PDF tests, and PR branch triggers | Upgrade in Phase 4 |
| `.gitignore` | Git ignore rules | Yes | Repo root | Ignores `.env`, `node_modules`, `__pycache__`, DB/uploads appropriately | Clean |
| `Dockerfile` | Monolithic container build | Yes | `backend/`, `frontend/` | Lacks Georgian Unicode fonts (`fonts-noto-core`, `fonts-dejavu-core`) for Linux ReportLab PDF generation | Upgrade in Phase 3 |
| `README.md` | Project overview & setup guide | Yes | Whole repo | Mentions stale Gemini 2.5 branding & minor setup gaps | Update in Phase 4 |
| `backend/.env.example` | Backend env template | Yes | `backend/app/config.py` | Needs Gemini 3.6/3.5 env docs | Update in Phase 3 |
| `backend/Dockerfile` | Backend service container | Yes | `backend/entrypoint.sh`, `requirements.txt` | Lacks `fonts-noto-core` / `fonts-dejavu-core` for Linux Georgian PDF rendering | Upgrade in Phase 3 |
| `backend/alembic.ini` | Alembic migration config | Yes | `backend/alembic/env.py` | Standard logging & script location; clean | Clean |
| `backend/alembic/README` | Alembic directory note | Yes | — | 1-line boilerplate | Clean |
| `backend/alembic/env.py` | Alembic runtime environment & metadata loader | Yes | `app.config.DATABASE_URL`, `app.db.models` | Reads `DATABASE_URL` dynamically; supports `render_as_batch=True` for SQLite | Clean |
| `backend/alembic/script.py.mako` | Migration file template | Yes | `sqlmodel` | Imports `sqlmodel` cleanly | Clean |
| `backend/alembic/versions/75cd228268f5_initial_schema.py` | Initial DB schema migration | Yes | SQLAlchemy/Alembic | Matches initial core tables | Clean |
| `backend/alembic/versions/a8f91e34c201_multi_user_platform_schema.py` | Multi-user isolation & `UserJobMatch` migration | Yes | `users`, `user_job_matches`, etc. | Properly adds `user_id` & `email_hash` indexes | Clean |
| `backend/alembic/versions/b9f4e21a8d10_ai_observability_cv_versions.py` | AI logs, cache, CV versions migration | Yes | `ai_usage_logs`, `ai_cache_entries`, `cv_versions` | Notice `ai_cache_entries.cache_key` uniqueness must include tenant/context isolation | Keep + add `applied_at` nullable migration |
| `backend/entrypoint.sh` | Container entrypoint running migrations + uvicorn | Yes | `alembic`, `uvicorn` | Clean `alembic upgrade head && exec uvicorn ...` | Clean |
| `backend/pytest.ini` | Pytest configuration | Yes | `pytest` | Triggers `asyncio_default_fixture_loop_scope` deprecation warning; set explicit scope | Update in Phase 4 |
| `backend/requirements.txt` | Python dependency pins | Yes | PyPI packages | Has `google-genai>=0.1.0`, `fastapi`, `sqlmodel`, `reportlab`, `python-docx`, `pypdf` | Verify / add `ruff` or keep CI tool clean |
| `backend/run.py` | Local Uvicorn dev runner | Yes | `app.config`, `uvicorn` | Clean Windows Proactor loop setup for Playwright | Clean |
| `backend/scripts/create_admin.py` | CLI super-admin bootstrapper | Yes | `auth_service.get_user_by_email` | Uses safe `get_user_by_email` & `hash_password`; clean | Clean |
| `docs/ARCHITECTURE.md` | Architecture reference | Yes | Backend/Frontend/Extension | Needs update to reflect Gemini 3.x, zero-fabrication ground truth, lifecycle & extension permissions | Update in Phase 4 |
| `docs/DEPLOYMENT.md` | Deployment guide | Yes | `render.yaml`, `Dockerfile`, Vercel | Line 41-42 still mandates `GEMINI_MODEL=gemini-2.5-flash` | Update in Phase 4 |
| `docs/EXTENSION.md` | Extension architecture & permissions guide | Yes | `extension/` | Claimed no `<all_urls>` permission while `manifest.json` actually requested `*://*/*` | Align in Phase 4 |
| `package.json` | Root workspace helper scripts | Yes | `frontend/`, `backend/` | Convenience wrapper scripts; clean | Clean |
| `render.yaml` | Render IaC blueprint | Yes | `backend/Dockerfile` | Sets `ENVIRONMENT=production` without `ENCRYPTION_KEY`, still specifies `gemini-2.5-flash` | Fix in Phase 3 |

### 3.2 Backend Configuration, DB & Schemas
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `backend/app/config.py` | Settings, paths, URL/SMTP helpers, Gemini config | Yes | `.env`, `os` | Defaults `GEMINI_MODEL="gemini-2.5-flash"` (retired/deprecated) and lacks dedicated `GEMINI_FAST_MODEL` (`gemini-3.5-flash-lite`) & timeout config | Fix in Phase 3 |
| `backend/app/main.py` | FastAPI app initialization, CORS, security headers, router registration | Yes | All routers, `init_db`, `gemini_service` | Hardcodes `"live_gemini_2.5_flash"` in `/api/health` (L157); otherwise clean CSP/security middleware | Fix in Phase 3 |
| `backend/app/db/__init__.py` | DB package exports | Yes | `database.py`, `models.py` | Clean re-exports | Clean |
| `backend/app/db/database.py` | Engine setup, SQLite WAL pragmas, `init_db()`, cleanup helpers | Yes | `config.DATABASE_URL`, `models` | Clean SQLite schema patching & cascade helpers | Clean |
| `backend/app/db/models.py` | SQLModel ORM tables with encrypted PII columns | Yes | `crypto_service`, `sqlmodel` | `ApplicationRecord.applied_at` defaults non-null `utc_now` even for `STAGED`/`SAVED` rows; `CandidateProfile` needs explicit `experience_status` / nullable `experience_years` | Fix in Phase 2/3 + Alembic migration |
| `backend/app/db/profile_repository.py` | Candidate ground-truth store, preset helpers, `CandidateProfile` persistence | Yes | `models`, `auth_service` | **C-01:** Line 218 queries `User.email == target` against encrypted ciphertext! Also needs strict separation between verified user ground-truth and optional `PROFESSION_MD_PRESETS` demos | Fix in Phase 2 |
| `backend/app/db/session.py` | Session dependency re-export | Yes | `database.py` | Clean wrapper | Clean |
| `backend/app/db/tracker_repository.py` | CRUD/Kanban repository for `ApplicationRecord` & `ApplicationTracker` | Yes | `models.py` | Stamps `applied_at` indiscriminately on stage creation instead of only submitted/applied states | Fix in Phase 3 |
| `backend/app/schemas/__init__.py` | Schemas package export | Yes | `api_schemas.py` | Clean | Clean |
| `backend/app/schemas/api_schemas.py` | Pydantic request/response DTOs | Yes | `routers/*` | Check defaults on `ProfileUpdateSchema`, `StageRequest`, `MatchAuditResponse` so unverified defaults aren't injected as truth | Audit & tighten in Phase 2 |

### 3.3 Backend Routers
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `backend/app/routers/admin.py` | Admin user management & AI cost/telemetry endpoints | Yes | `auth_service`, `AIUsageLog`, `ApplicationRecord` | Clean RBAC admin gating & masked PII stats | Clean |
| `backend/app/routers/answers.py` | Screening answer retrieval endpoints | Yes | `answer_service`, `auth_service` | Passes current user context to `answer_service` (service failed to pass `user` down) | Fix paired service in Phase 2 |
| `backend/app/routers/audit.py` | Candidate & vacancy audit endpoints | Yes | `audit_service`, `auth_service` | Aggregates experience/profile defaults via `audit_service` | Clean once `audit_service` fixed |
| `backend/app/routers/auth.py` | Login, register, OTP verification, refresh tokens, Google OAuth/Calendar | Yes | `auth_service`, `gmail_service`, `crypto_service` | Solid HMAC OTP rate-limit + refresh token rotation; minor Starlette `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning | Minor cleanup |
| `backend/app/routers/b2b.py` | Georgia IE 1%/3% tax calculator, FX rates, timezone overlap, invoice & B2B proposals | Yes | `gemini_service`, `profile_repository`, `httpx` | Real NBG FX + tax math; uses `gemini_service` for proposals | Fix minor default fallback if any |
| `backend/app/routers/extension.py` | Chrome extension analyze, autofill answers, CV package, save-job API | Yes | `matcher_service`, `cv_generator_service`, `answer_service` | **C-04:** Line 267 defaults `experience_years or 1.5` | Fix in Phase 2 |
| `backend/app/routers/ground_truth.py` | Profile CRUD, `.pdf`/`.docx`/`.md` resume parsing, preset switcher, action plan | Yes | `profile_service`, `cv_parser_service`, `plan_service`, `profile_repository` | Expose clear file format errors (reject `.doc`), protect real user profiles against unintended preset overwrite, clean profile-to-CV sync | Harden in Phase 2 |
| `backend/app/routers/jobs.py` | Paged jobs feed (`b2b_only`, `geo_eligible_only`, tier counts), manual scrape trigger | Yes | `scraper_orchestrator`, `matcher_service`, `UserJobMatch` | Well-indexed pagination + `UserJobMatch` user scoping | Keep + verify |
| `backend/app/routers/plans.py` | Upskilling action plan CRUD & regeneration | Yes | `plan_service`, `auth_service` | Clean auth scoping; underlying `plan_service` needs non-QA domain neutrality | Fix `plan_service` in Phase 2 |
| `backend/app/routers/stage.py` | Playwright form staging endpoint | Yes | `playwright_service`, `link_validator` | Clean SSRF check + router dispatch | Clean |
| `backend/app/routers/tracker.py` | Application tracker, Kanban move, Calendar sync, Gmail dispatch, backup export/import | Yes | `tracker_repository`, `gmail_service`, `backup_service` | **C-06:** Line 79 falls back invalid ID strings to `app_id = 1`! Must return HTTP 400 | Fix in Phase 2 |

### 3.4 Backend Services & Scrapers
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `backend/app/services/answer_service.py` | Screening Q&A generation & persistence | Yes | `ground_truth_store`, `config` | **C-02/C-04:** Calls `ground_truth_store.get_data()` with no `user_id`/`owner_email` (cross-user leak); defaults `"1 week after offer"` | Fix in Phase 2 |
| `backend/app/services/audit_service.py` | Vacancy requirements audit & candidate readiness checks | Yes | `profile_repository`, `matcher_service` | **C-04:** Line 298 coerces missing `experience_years` to `1.5` | Fix in Phase 2 |
| `backend/app/services/auth_service.py` | Password hashing, JWT issue/verify, `get_user_by_email`, OAuth state | Yes | `jose`, `passlib`/`bcrypt`, `crypto_service` | Strong `blind_index` email lookup & guest isolation | Clean |
| `backend/app/services/backup_service.py` | Encrypted/JSON vault export & restore | Yes | `models`, `crypto_service` | Clean scoped export/import | Clean |
| `backend/app/services/company_validator.py` | Employer legitimacy & scam/agency heuristics | Yes | `JobPosting` | Clean rule checks | Clean |
| `backend/app/services/crypto_service.py` | Fernet encryption, key rotation, HMAC blind index | Yes | `cryptography.fernet` | Solid; enforces explicit `ENCRYPTION_KEY` in production (matches `render.yaml` gap) | Clean |
| `backend/app/services/cv_generator_service.py` | Tailored `.docx`, `.pdf`, HTML CV, Cover Letter, Motivational Letter generation | Yes | `python-docx`, `reportlab`, `gemini_service`, `profile_repository` | **C-04/H-02:** Hardcodes `"QA_Engineer"`, `"qa_tech"`, `"1 week after offer"`, `"Manual QA, REST API, Test Design"`, `1.5` years fallback, template Cover/Motivational letter overlap, missing verification guard & Linux Georgian font guarantee | Rebuild in Phase 3 |
| `backend/app/services/cv_parser_service.py` | Extracts text from `.pdf`, `.docx`, `.md`, `.txt` | Yes | `pypdf`, `python-docx`, `zipfile` | **M-01:** Missing DOCX zip-bomb uncompressed XML size guard; should explicitly reject binary `.doc` with helpful error | Fix in Phase 2 |
| `backend/app/services/gemini_service.py` | Gemini LLM client, AI JSON generation, DB cache, telemetry logging | Yes | `google.genai`, `AIUsageLog`, `AICacheEntry` | **C-05:** Uses `gemini-2.5-flash` defaults, omits `HttpOptions(timeout=...)`, sets `temperature` globally without 3.x differentiation, weak untrusted job-text isolation, cache keys should include user/version boundaries | Upgrade in Phase 3 |
| `backend/app/services/gmail_service.py` | Gmail API / SMTP dispatch & `.eml` fallback, Google Calendar ICS/Event creation | Yes | `httpx`, `config`, `auth` | Clean non-simulated `.eml` fallback & calendar event creation | Clean |
| `backend/app/services/interview_service.py` | Role-specific interview preparation Q&A | Yes | `gemini_service`, `profile_repository` | Check for hardcoded `1.5` or QA assumptions in heuristic fallbacks | Fix in Phase 2 |
| `backend/app/services/link_validator.py` | SSRF protection (blocks loopback/RFC1918/metadata IPs, validates URL scheme) | Yes | `ipaddress`, `socket`, `urllib` | Strong multi-layer SSRF protection | Clean |
| `backend/app/services/matcher_service.py` | Multi-tier scoring (`DIRECT`, `ADJACENT`, `PUBLIC_INTERNSHIP`), seniority & stack fit | Yes | `profile_service`, `salary_service` | **C-04:** Injects `years_of_experience: 1.5` (L176,186,227,536,618) and assumes `["English", "Georgian"]` | Fix in Phase 2 |
| `backend/app/services/plan_service.py` | Skill gap & learning roadmap generator | Yes | `profile_repository`, `gemini_service` | **C-04:** Defaults non-QA/unknown domain skill gaps to QA/Docker/k6 | Fix in Phase 2 |
| `backend/app/services/playwright_service.py` | Browser form autofill staging (pauses before CAPTCHA/submit) | Yes | `playwright`, `link_validator`, `portal_detector` | **C-04:** Hardcodes `"1 week after offer"`, `"1.5+ years..."`, blind `.select_option(value="yes")` for work authorization | Fix in Phase 2 |
| `backend/app/services/portal_detector.py` | Portal identification & title/company extraction from DOM/URL | Yes | `re`, `bs4` | **C-04:** Defaults unknown title/company to `"Senior QA Automation Engineer"` and `"Tech Company"` | Fix in Phase 2 |
| `backend/app/services/profile_service.py` | Markdown/structured profile parser & industry/experience extractor | Yes | `profile_repository`, `crypto_service` | **C-01/C-04:** Uses `User.email == target` (L543), forces missing `years_of_experience` to `1.5` (L348-350), defaults `spoken_languages` to `["English", "Georgian"]` (L469) | Fix in Phase 2 |
| `backend/app/services/salary_service.py` | Vacancy salary extractor & currency normalization (`GEL`, `USD`, `EUR`) | Yes | `re` | Clean regex extraction; handles `ლარი` -> `GEL` accurately | Clean |
| `backend/app/services/scrapers/__init__.py` | Scraper module exports | Yes | `scrapers/*` | Clean | Clean |
| `backend/app/services/scrapers/ats_board_scraper.py` | Greenhouse & Lever JSON board scrapers | Yes | `httpx` | Clean structured API parsing | Clean |
| `backend/app/services/scrapers/base_scraper.py` | Base HTTP scraper helpers & Georgia B2B suitability classifier | Yes | `httpx`, `bs4` | Clean GE local / REMOTE_B2B / REGION_LOCKED classification | Clean |
| `backend/app/services/scrapers/djinni_scraper.py` | Djinni.co scraper | Yes | `base_scraper` | Clean HTML parsing & URL checks | Clean |
| `backend/app/services/scrapers/dou_scraper.py` | DOU.ua scraper | Yes | `base_scraper` | Clean parsing | Clean |
| `backend/app/services/scrapers/headhunter_scraper.py` | HeadHunter API/HTML scraper | Yes | `base_scraper` | Clean parsing | Clean |
| `backend/app/services/scrapers/hr_ge_scraper.py` | HR.ge scraper | Yes | `base_scraper` | Clean parsing | Clean |
| `backend/app/services/scrapers/hr_gov_scraper.py` | HR.gov.ge Georgian public internship scraper | Yes | `base_scraper` | Clean table parsing & deadlines | Clean |
| `backend/app/services/scrapers/jobs_ge_scraper.py` | Jobs.ge Georgian board scraper | Yes | `base_scraper` | Clean query filtering & cid mapping | Clean |
| `backend/app/services/scrapers/justjoin_scraper.py` | JustJoin.it scraper | Yes | `base_scraper` | Clean API parsing | Clean |
| `backend/app/services/scrapers/linkedin_scraper.py` | LinkedIn guest jobs scraper | Yes | `base_scraper` | **M-02:** Unconditionally filters out ALL `Senior`/`Lead`/`3+` yr roles even if candidate actually has senior experience | Parameterize in Phase 2 |
| `backend/app/services/scrapers/query_builder.py` | Domain-aware search query builder across portals | Yes | `profile_service` | **C-04:** Line 184 coerces missing `years_of_experience` to `1.5` | Fix in Phase 2 |
| `backend/app/services/scrapers/remote_b2b_scrapers.py` | Remotive, Himalayas, RemoteOK JSON scrapers | Yes | `base_scraper` | **M-02:** Line 175 uses `hash(url)` (salted per-process) & lacks explicit `https://` scheme validation | Fix in Phase 2 |
| `backend/app/services/scrapers/scraper_orchestrator.py` | Orchestrates scrapers, deduplication, per-user matching & serialization | Yes | `scrapers/*`, `matcher_service`, `models` | **C-02/C-03:** Falls back to arbitrary user's `CandidateProfile` (L353-358) AND auto-creates fake `ApplicationRecord` entries on ingestion (L577-595) | Fix in Phase 2/3 |

### 3.5 Frontend (`frontend/`)
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `frontend/.env.example` | Frontend env template | Yes | Vite | `VITE_API_URL` clean | Clean |
| `frontend/index.html` | HTML entry point + Google Fonts (Noto Sans Georgian) | Yes | Vite | Includes Georgian font support | Clean |
| `frontend/package.json` & `package-lock.json` | React/Vite/Tailwind/Lucide dependencies & lockfile | Yes | npm | Build clean (`vite`, `typescript`, `lucide-react`, `@dnd-kit/*` if used) | Clean |
| `frontend/postcss.config.js` | PostCSS plugins | Yes | Tailwind | Standard config | Clean |
| `frontend/tailwind.config.js` | Tailwind theme colors/fonts | Yes | `index.css` | Clean | Clean |
| `frontend/tsconfig.json` & `tsconfig.node.json` | Strict TypeScript configuration | Yes | `src/` | Clean; should be invoked via `tsc --noEmit` in CI | Add `tsc` to CI |
| `frontend/vercel.json` | Vercel SPA rewrites | Yes | — | Clean | Clean |
| `frontend/vite.config.ts` | Vite dev proxy & build config | Yes | React plugin | Proxies `/api` cleanly in dev | Clean |
| `frontend/src/main.tsx` | React root mount | Yes | `App.tsx`, `index.css` | Clean | Clean |
| `frontend/src/index.css` | Global styles, theme palette, accessibility focus styles | Yes | Tailwind | Clean high-contrast focus outlines & Georgian typography support | Clean |
| `frontend/src/types/index.ts` | Shared TypeScript interfaces | Yes | Backend schemas | Align nullable `experience_years` & `experience_status` types | Update in Phase 2/4 |
| `frontend/src/services/api.ts` | Typed Fetch API client with cookie/bearer auth & refresh handling | Yes | `types/index.ts` | Clean refresh-token retry logic; ensure `search` query param supported cleanly | Verify/update in Phase 4 |
| `frontend/src/App.tsx` | Top-level SPA router, auth gate, tab layout | Yes | All components | Clean responsive layout & auth recovery | Clean |
| `frontend/src/components/Navbar.tsx` | Top navigation & user/admin menu | Yes | `App.tsx` | Minor aria/navigation polish if needed | Polish in Phase 4 |
| `frontend/src/components/DashboardHome.tsx` | Main metrics & quick-action landing view | Yes | `api.ts` | **M-03:** `text-slate-500` low contrast on dark background | Polish contrast in Phase 4 |
| `frontend/src/components/DiscoveryFeed.tsx` | Paginated vacancy explorer with Direct/Adjacent/Public filters | Yes | `api.ts` | **C-04/H-05:** Hardcodes `?? 1.5` & `Math.min(expVal + 0.5, 2.0)`; pagination bar slices only pages `1..5` | Fix in Phase 4 |
| `frontend/src/components/AuditPanel.tsx` | Detailed vacancy audit, skills comparison & quick CV build | Yes | `api.ts` | **C-04/C-06/H-05:** `?? 1.5`/`?? 2.0`, advertises `.doc`, `loadPagedJobs()` calls drop `b2bOnlyFilter` & `geoEligibleOnlyFilter` state | Fix in Phase 4 |
| `frontend/src/components/ApplicationTracker.tsx` | Kanban drag-and-drop tracker, calendar sync, Gmail dispatch | Yes | `api.ts`, `EmailDispatchModal`, `InterviewPrepModal` | Clean drag-drop Kanban + separate Rejected stage; displays clean empty/unapplied state once backend stops faking `STAGED` rows | Verify after C-03 fix |
| `frontend/src/components/CVVariantManager.tsx` | CV `.docx`/`.pdf` builder, preview, Cover/Motivational Letter generator | Yes | `api.ts` | **C-06/H-04:** Fetches up to 1,000 jobs eagerly on mount (L116-128), `triggerCrossOriginDownload` prints `"Downloaded!"` despite errors, unawaited `navigator.clipboard.writeText`, advertises `.doc` | Fix in Phase 4 |
| `frontend/src/components/ProfileVault.tsx` | `skills.md` editor, CV upload, parsed education/skills viewer | Yes | `api.ts` | **C-06/M-03:** Accepts `.doc` in file input (L220), shows `"e.g. 1 week after offer"` placeholder (L558), missing `aria-label` (L623) | Fix in Phase 4 |
| `frontend/src/components/StageModal.tsx` | Playwright form-staging modal | Yes | `api.ts` | **C-06/H-05:** Renders `href={urlInput}` without `http(s)://` scheme check; inverted `Pause for Final Review` switch (`checked={autoSubmit}`) | Fix in Phase 4 |
| `frontend/src/components/ActionPlanView.tsx` | Upskilling roadmap checklist | Yes | `api.ts` | **M-03:** Uses blocking `alert()`, clickable non-button `<div>` (L206) | Fix in Phase 4 |
| `frontend/src/components/AdminDashboard.tsx` | Admin telemetry & user governance dashboard | Yes | `api.ts` | **M-03:** Uses `alert()` dialogs | Replace with inline status banner in Phase 4 |
| `frontend/src/components/AuthModal.tsx` | Login, Register & OTP modal | Yes | `api.ts` | Clean accessible form handling | Clean |
| `frontend/src/components/EmailDispatchModal.tsx` | Gmail / SMTP / `.eml` composer modal | Yes | `api.ts` | **M-03:** Uses `alert()` dialogs | Replace with inline status banner in Phase 4 |
| `frontend/src/components/InterviewPrepModal.tsx` | Technical/behavioral interview Q&A modal | Yes | `api.ts` | **C-04/M-03:** Hardcodes `"Technical QA / SDET"` fallback + uses `alert()` | Fix in Phase 4 |
| `frontend/src/components/B2BMarketHub.tsx` | Georgia IE 1%/3% tax calculator, timezone matrix & invoice generator | Yes | `api.ts` | Strong genuine tax/FX/timezone functionality | Clean |

### 3.6 Chrome Extension (`extension/`)
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `extension/manifest.json` | MV3 extension manifest | Yes | Chrome MV3 APIs | **H-03:** Requests wildcard `"https://*/*"`, `"http://*/*"` in `host_permissions` | Restrict to `optional_host_permissions` + supported hosts in Phase 4 |
| `extension/background/service_worker.js` | Extension background API bridge & tab permission router | Yes | `manifest.json`, Backend API | Update to cooperate cleanly with optional runtime host permissions | Update in Phase 4 |
| `extension/content/content.js` | DOM job extractor & form autofill content script | Yes | DOM selectors | Captures job description/fields cleanly without auto-submitting or bypassing CAPTCHA | Clean |
| `extension/content/content.css` | Injected HUD & field highlight styles | Yes | `content.js` | Clean isolated styles | Clean |
| `extension/popup/popup.html` | Extension popup UI | Yes | `popup.js`, `popup.css` | Clean HITL UI | Clean |
| `extension/popup/popup.css` | Extension popup styles | Yes | `popup.html` | Clean dark high-contrast palette | Clean |
| `extension/popup/popup.js` | Popup controller, auth, job analysis, CV download & autofill | Yes | `service_worker.js`, `api` | **C-04/H-03:** Displays fallback `1.5 yrs` when experience is null/unknown; request host permission cleanly when scanning non-pregranted ATS pages | Fix in Phase 4 |
| `extension/icons/icon16.png`, `icon48.png`, `icon128.png` | Extension icons | Yes (tracked asset list) | `manifest.json` | Binary PNG icon assets | Clean |

### 3.7 Automated Tests & Fixtures (`backend/tests/`, `tests/`)
| File Path | Purpose | Reviewed | Key Dependencies | Findings | Fix Status |
|---|---|---|---|---|---|
| `backend/tests/conftest.py` | Isolated temporary SQLite DB fixture | Yes | `app.db.database` | Clean per-process isolation | Clean |
| `backend/tests/fixtures/forms/*.html` (`djinni`, `dou`, `greenhouse`, `jobs_ge`, `justjoin`, `lever`) | Offline ATS form HTML fixtures for Playwright tests | Yes | `test_playwright_forms.py` | Clean offline test fixtures (note: Playwright should avoid unverified fabrications on them) | Keep cleanly aligned |
| `backend/tests/test_ai_telemetry_and_parsing.py` | Tests `.pdf`/`.docx`/`.md` parsing, Gemini telemetry & cache | Yes | `cv_parser_service`, `gemini_service` | Extend with zip-bomb/legacy `.doc` rejection, Gemini 3.x model checks & prompt nonce isolation | Extend in Phase 5 |
| `backend/tests/test_answers.py` | Screening Q&A tests | Yes | `answer_service` | **Test encodes bug:** Asserts `"1 week after offer"`, `38000` salary & unverified auth + ignores multi-user isolation | Update & expand in Phase 5 |
| `backend/tests/test_audit.py` | Candidate/job audit tests | Yes | `audit_service` | **Test encodes bug:** Expects hardcoded `"1 week after offer"`, `38000`, `"Yes"` | Update in Phase 5 |
| `backend/tests/test_auth_admin_copilot.py` | Auth, OTP, Admin stats & Copilot endpoints | Yes | `auth`, `admin`, `extension` | Good coverage | Keep + re-run |
| `backend/tests/test_b2b_and_demock.py` | Tax calculator, timezone matrix, real `.eml`, `UserJobMatch` isolation & B2B scrapers | Yes | `b2b`, `gmail_service`, `remote_b2b_scrapers` | Good real isolation checks | Keep + re-run |
| `backend/tests/test_cv_education_calendar_kanban.py` | Education block, Kanban columns, calendar sync | Yes | `cv_generator_service`, `tracker` | Good coverage of TSU education & Kanban | Keep + re-run |
| `backend/tests/test_cv_versions_and_letters.py` | CV versioning, Cover vs Motivational letter tests | Yes | `cv_generator_service` | Extend with multi-profession DOCX/PDF text extraction (`pypdf`/`python-docx`) & Cover vs Motivational distinction checks | Extend in Phase 5 |
| `backend/tests/test_database_and_scrapers.py` | SQLite persistence, query builder & scraper orchestration | Yes | `scraper_orchestrator` | **Test encodes bug (L357-359):** Asserts `len(app_records) >= 3` auto-created after scraping! | Update to verify zero auto-applications in Phase 5 |
| `backend/tests/test_linkedin_and_extension.py` | LinkedIn scraper & Chrome extension API tests | Yes | `linkedin_scraper`, `extension` | Update/extend to confirm adaptive seniority filtering & non-1.5 exp display | Extend in Phase 5 |
| `backend/tests/test_master_architecture_and_isolation.py` | Multi-user isolation & notes CRUD | Yes | `auth`, `tracker` | Good coverage | Keep + re-run |
| `backend/tests/test_optimization_alembic_pagination.py` | Pagination, DB indexing, Alembic schema parity | Yes | `alembic`, `jobs` | Good schema verification | Re-run after new migration |
| `backend/tests/test_playwright_forms.py` | Offline Playwright staging checks (`dou`, `greenhouse`, `lever`) | Yes | `playwright_service` | Keep passing after `playwright_service` zero-fabrication fix | Update assertion for explicit start date vs confirmed |
| `backend/tests/test_security_and_isolation.py` | Tenant isolation & PII access checks | Yes | `profile_repository`, routers | Extend with `AnswerService` & `ScraperOrchestrator` isolation regression tests | Extend in Phase 5 |
| `backend/tests/test_seniority_otp_liveness.py` | Seniority cap, OTP rate limit, DB encryption at rest | Yes | `matcher_service`, `crypto_service` | Good encrypted column verification | Keep + re-run |
| `backend/tests/test_stage.py` | `/api/stage-application` API integration check | Yes | `stage` router | Good offline staging check | Keep + re-run |
| `backend/tests/test_tier_counts_and_domain_adaptation.py` | Tier counts & non-IT domain adaptation | Yes | `matcher_service`, `jobs` | Good domain checks | Keep + re-run |
| `backend/tests/test_ux_polish_and_docx.py` | DOCX OOXML font checks, Georgian GEL normalization, preset cleanup | Yes | `cv_generator_service`, `jobs` | Ensure presets tested explicitly as opt-in demo & non-QA works | Keep + verify |
| `tests/conftest.py` | Root non-functional pytest config | Yes | `backend` path | Clean | Clean |
| `tests/non_functional/k6_stress.js` | k6 load-test script | Yes | `/health`, `/api/jobs` | Add proper HTTP checks / threshold coverage aligned with FastAPI routes | Update in Phase 4 |
| `tests/non_functional/test_a11y_and_perf.py` | Static/Playwright frontend accessibility & render checks | Yes | `frontend/` | Keep passing + extend checks if helpful | Run in Phase 5 |
| `tests/non_functional/test_security.py` | SQLi, SSRF, path traversal, JWT/CSP security suite | Yes | `backend` app | All 7 tests pass in baseline | Re-run in Phase 5 |
| `data/resumes/resume_*.pdf` (3 sample PDFs) | Tracked fixture PDFs for offline resume parser testing | Yes (tracked asset list) | `cv_parser_service` | Used by parser/fixture tests | Keep (not used as live defaults) |

---

## 4. Executed Remediation & Verification Summary

All Phases 2–5 changes listed in Section 2 (`C-01`..`C-06`, `H-01`..`H-05`, `M-01`..`M-04`) have been implemented on branch `agent/full-quality-and-cv-trust` with full regression coverage added in `backend/tests/test_quality_and_cv_trust.py` and schema updates in `backend/alembic/versions/c4e8a12f9b30_nullable_applied_at_and_experience_years.py`:

### Final Post-Edit Verification Results (Directly Observed)
| Check | Scope | Result |
|---|---|---|
| Backend Functional & Unit Suite (`python -m pytest tests -q --tb=short` from `backend/`) | All 17 test modules including `test_quality_and_cv_trust.py`, clean CI checkout simulation (`SKILLS_MD_FILE` absent), Playwright offline form tests, DOCX/PDF binary extraction (`python-docx` / `pypdf`), isolation, auth/bcrypt/OTP throttling, country/city & geo pagination, CV upload isolation, ATS role-tag filenames, & non-masked migration checks | **93 passed in 34.48s** (`0 failed`, `0 skipped`) |
| Security & Exploit-Resistance Suite (`python -m pytest tests/non_functional/test_security.py -v --tb=short`) | SQLi, auth/refresh token isolation, brute-force rate limit, SSRF block, path traversal, headers, CSP & production guest block | **7 passed in 6.74s** (`0 failed`) |
| Accessibility, Mobile Layout & Perf Suite (`python -m pytest tests/non_functional/test_a11y_and_perf.py -v --tb=short`) | Live preview + API servers (`127.0.0.1:8000` & `127.0.0.1:5173`), headless Chromium load timing, console errors, mobile overflow, axe-core WCAG 2.1 AA | Re-verified after commit |
| Fresh Alembic Migration (`alembic upgrade head` on clean SQLite DB) | Upgrades through `75cd228268f5 -> a8f91e34c201 -> b9f4e21a8d10 -> c4e8a12f9b30` | **Exit code 0** |
| Frontend Typecheck & Production Build (`npx tsc --noEmit && npm run build`) | Full TypeScript strict compilation and Vite bundle (`1587 modules`) | **Exit code 0** (`✓ built in 6.14s`) |
| Chrome Extension Syntax & Manifest Check (`node --check` on JS + JSON parse of `manifest.json`) | `service_worker.js`, `content.js`, `popup.js`, `manifest.json` | **Exit code 0** (`manifest valid`) |
| Local Static Python Lint (`python -m ruff --version`) & Live `k6` Load Benchmark | Host `miniconda3` does not have `ruff` installed (`No module named ruff`); `.github/workflows/ci.yml` invokes `ruff check app tests --select E9,F63,F7,F82` (unsupported `--show-source` removed); `tests/non_functional/k6_stress.js` route alignment verified statically | Deferred to CI (`ruff`) / staging (`k6`) |

---

## 5. CI Log & Static Review Remediation Follow-Up

The following CI failures and static-review findings were resolved and verified with automated regression tests in `backend/tests/test_quality_and_cv_trust.py` and `backend/tests/test_tier_counts_and_domain_adaptation.py`:

| Issue | Root Cause | Resolution Implemented |
|---|---|---|
| `passlib` + modern `bcrypt` CI failure (`45` tests) | `passlib 1.7.4` fails under `bcrypt >= 4.1` (`__about__` AttributeError and >72-byte wrap self-test ValueError). | Removed `passlib[bcrypt]` from `backend/requirements.txt` and migrated `backend/app/services/auth_service.py` to direct `bcrypt` (`hashpw`/`checkpw`) preserving `$2b$` compatibility. |
| Passwords `> 72` UTF-8 bytes causing HTTP `500` on registration | `RegisterRequest` and `hash_password` lacked byte-length checks before `bcrypt.hashpw`. | Added explicit `<= 72` UTF-8 byte validation (`RegisterRequest` validator returning `422`, `ValueError` in `hash_password`, safe `False` in `verify_password`, and frontend check in `AuthModal.tsx`). |
| Missing `data/candidate_skills.md` in CI checkout (`FileNotFoundError`) | `test_cv_education_calendar_kanban.py` read gitignored `data/candidate_skills.md`. | Added tracked anonymized fixture `backend/tests/fixtures/tsu_candidate_skills.md` and switched `test_cv_education_calendar_kanban.py` to load it cleanly. |
| Tier/status counts test isolation & `min_score=60` coverage | `test_global_tier_and_status_counts` selected an arbitrary `CandidateProfile.first()` and skipped non-applied cleanup cleanly. | Scoped `CandidateProfile` strictly to `test_user.id`, cleaned prior jobs via `delete_job_posting_cascade`, and verified both default `min_score=60` and explicit `min_score=0`. |
| `/request-otp` did not increment rate-limit counter | `send_otp_code` called `check_rate_limit` without incrementing or separating buckets. | Added atomic `consume_rate_limit` on dedicated `otp_request:{email}` (+ coarse per-IP bucket) in `auth.py` and `auth_service.py`. |
| Job `country`/`city` filters & `geo_eligible_only` pagination mismatch | `country`/`city` only matched `JobPosting.market`; `geo_eligible_only` filtered after DB `.offset().limit()`. | Filtered against `JobPosting.country`/`city` (with fallback when unset), passed full location string into `classify_georgia_b2b_suitability`, and evaluated `geo_eligible_only` before computing `tier_counts`, `status_counts`, `total`, `total_pages`, and page slice. |
| Cross-user CV upload filename collision | `USER_CV_DIR / safe_name` and unscoped `CandidateDocument.filename` queries allowed overwrites/reassignment. | Stored personal CVs under per-user folders (`USER_CV_DIR / user_{id}`), scoped `CandidateDocument` lookup/deletion by `user_id` + `doc_type`, and rejected `.doc` uploads cleanly. |
| Masked Alembic migration failures in `init_db` | `init_db()` caught Alembic errors and fell back to `SQLModel.metadata.create_all()`. | Enforced strict Alembic failure propagation (`RuntimeError`) in `backend/app/db/database.py` (using `create_all()` only for `:memory:` or absent `alembic.ini`) and preserved programmatic URLs in `backend/alembic/env.py`. |
| ATS filename mismatch in clean CI (`Candidate_Specialist_ATS_KA.docx` vs `QA_Engineer_ATS`) | `test_jobsge_location_never_parsed_as_company_and_clean_highlights` relied on shared guest/seeded `data/candidate_skills.md` profile, and `skills_md_override` did not refresh `target_industry`/`primary_role` taxonomy. | Documented contract (`cv_style` `"ats"`/`"recruiter"` derive role tag from verified candidate profile; `"tailored"` uses target company & target role), updated `_extract_override_profile_taxonomy` / `_resolve_ats_role_tag` in `cv_generator_service.py`, isolated the test with explicit QA user setup & teardown, and added override contract assertions in `test_quality_and_cv_trust.py`. |

