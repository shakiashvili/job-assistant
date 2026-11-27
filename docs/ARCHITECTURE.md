# TalentFlow AI — System Architecture

## 1. High-Level Layers

1. **Frontend SPA (`frontend/`)**
   - Built with **React 18 + TypeScript + Tailwind CSS + Vite**, guarded by ESLint (`@typescript-eslint`, `react-hooks`, `jsx-a11y`), `tsc --noEmit`, and Vitest.
   - Auth gate on mount holds `isAuthChecking` while validating JWT access tokens and executing single-flight `HttpOnly`-cookie refresh (`POST /api/auth/refresh`) on `401`.
   - Core views:
     - `DashboardHome`: candidate funnel analytics (`GET /api/analytics/candidate`), profile completeness, integrations/DB health, and upcoming interviews.
     - `AuditPanel` + `DiscoveryFeed`: durable async multi-portal scanning (`POST /api/jobs/scrape/async` + status polling), composable server-side filtering, source health panel, explicit salary provenance (`Verified` / `Estimated` / `Not Listed`), cross-portal duplicate indicators, and one-click Gmail draft packages.
     - `ApplicationTracker`: Kanban pipeline (`SAVED` → `APPLIED` → `HR_SCREEN` → `TECH_INTERVIEW` → `FINAL_ROUND` → `OFFER` / `REJECTED`), `.ics` / Google Calendar integration, immutable document snapshots, and interactive STAR Mock Interview Copilot.
     - `CVVariantManager` (**CV Studio**): `.pdf` / `.docx` / `.md` / `.txt` vault storage, `/api/cv-versions` CRUD, blank/duplicate/compare views, ATS parseability check (`GET /api/cv-versions/{id}/ats-check`), and persisted **Cover Letter** & **Motivational Letter** tabs.
     - `ProfileVault`: manual section-by-section editor + safe import preview/merge (`POST /api/profile/import-preview`, `POST /api/profile/import-apply`) and profile intelligence diagnostics.
     - `B2BMarketHub` (gated by `ENABLE_B2B_HUB`): Georgia Article 90 1% vs. labor tax calculator, live/fallback NBG FX rates, and DST-aware Tbilisi (`UTC+4`) timezone overlap matrix.
     - `AdminDashboard`: RBAC-protected platform metrics and AI pipeline/cost telemetry (`GET /api/admin/ai-metrics`).

2. **Backend API (`backend/app/`)**
   - **FastAPI** application with SQLModel + SQLAlchemy + Alembic migrations (tested against both SQLite and PostgreSQL in CI).
   - **Thin Routers & Composable Services**:
     - `services/job_query_service.py`: `JobFilters` (`Depends()`) and composable SQLAlchemy filtering/sorting/pagination powering `GET /api/jobs/scraped`.
     - `services/matching/gates.py`: typed `GateResult` pipeline (`SeniorityGate`, `ExperienceGate`, `DisciplineGate`, `LanguageGate`, `run_gate_pipeline`).
     - `services/cv/context.py` + `services/cv_generator_service.py`: `CVRenderContext` dataclass + bilingual (`en` / `ka`) HTML, ReportLab PDF (Sylfaen/FreeSans/DejaVu Unicode fonts), and Word (`.docx`) builders.
     - `services/b2b_tax_service.py`: cited `GEO_TAX_CONFIG` + single async TTL-cached NBG FX fetcher.
   - **Centralized AI Gateway (`services/gemini_service.py`, `services/ai_schemas.py`, `prompts/`)**:
     - Verified Gemini models (`gemini-3.6-flash` quality / `gemini-3.5-flash-lite` fast) with optional free-tier OpenRouter fallback (`AI_ALLOW_PAID_FALLBACK=false` by default) and deterministic ground-truth heuristic fallback.
     - Versioned prompt templates in `backend/app/prompts/` recorded in `AIOperationLog.prompt_hash`.
     - Strict Pydantic response validation (`ExtractedJobDetailsSchema`, `NarrativePackageSchema`, `ScreeningAnswerListSchema`, `CompanyResearchSchema`, `TranslationListSchema`) with retry-once repair and `VALIDATION_ERROR` telemetry.
     - Safety controls: nonce-delimited untrusted input wrapping, `minimize_pii_for_llm()` redaction, `AI_DAILY_TOKEN_BUDGET_PER_USER`, explicit `AI_THIRD_PARTY_CONSENT_REQUIRED` gate, tenant+model+prompt-version SHA-256 caching with `AI_MAX_CACHE_ENTRIES` eviction cap, and production startup health probe (`verify_startup_model_health`).
   - **Offline Evaluation Harness (`backend/evals/`)**:
     - 30 labelled multi-industry job/profile cases in `golden_dataset.json` executed by `eval_runner.py` in CI, verifying seniority-gate precision/recall, domain accuracy, and zero-fabrication groundedness (`check_groundedness`).
   - **Multi-User Isolation & Security**:
     - Scoped `CandidateProfile` (Fernet-encrypted PII + `email_hash` blind index), `UserJobMatch`, `ApplicationTracker` (soft delete + hard purge), `SavedJob`, `SavedSearch`, `CandidateDocument`, `CVVersion`, and `SkillActionPlan`.
     - SSRF-validated outbound HTTP (`validate_safe_external_url` with injectable DNS resolver for hermetic tests), `HttpOnly` refresh cookies, signed OAuth JWT `state`, and admin RBAC.
     - Server-side Playwright auto-staging and server-side LinkedIn scraping are retired (`docs/DECISIONS.md`).

3. **Chrome Extension (`extension/`)**
   - **Manifest V3** Side Panel Copilot operating strictly inside the user's authenticated browser session (including LinkedIn and authenticated ATS portals).
   - Least-privilege permissions (`activeTab`, `scripting`, `storage`, `sidePanel`, `optional_host_permissions`), dynamic backend URL routing, editable answer pre-fill, and human-in-the-loop review before submission.
