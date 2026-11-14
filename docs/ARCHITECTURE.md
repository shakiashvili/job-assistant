# TalentFlow AI — System Architecture

## 1. High-Level Layers

1. **Frontend SPA (`frontend/`)**
   - Built with **React + TypeScript + Tailwind CSS + Vite**.
   - Auth gate on mount holds `isAuthChecking` while validating JWT access tokens and executing single-flight refresh (`POST /api/auth/refresh`) on `401`.
   - Core views:
     - `DashboardHome`: real candidate funnel analytics (`GET /api/analytics/candidate`), profile completeness meter, missing Ground Truth checklist, and upcoming interviews.
     - `AuditPanel` + `DiscoveryFeed`: async multi-portal scanning (`POST /api/jobs/scrape/async` + status polling), strict seniority & remote/location gates, explicit salary provenance (`Verified` / `AI Estimated` / `Not Listed`), and one-click Gmail package drafting.
     - `ApplicationTracker`: multi-stage Kanban pipeline (`SAVED` → `STAGED` → `APPLIED` → `HR_SCREEN` → `TECH_INTERVIEW` → `FINAL_ROUND` → `OFFER` / `REJECTED`), interview scheduling, and AI Interview Copilot (`STAR` briefs).
     - `CVVariantManager` (**CV Studio**): `.pdf` / `.docx` / `.md` / `.txt` vault storage, ATS/Recruiter/Job-Tailored Word + PDF builder, saved `CVVersion` switcher with inline editing + live HTML/PDF/DOCX re-rendering, and distinct **Cover Letter** vs **Motivational Letter** tabs.
     - `ProfileVault`: Ground Truth editor with universal CV upload & missing-field diagnostics.
     - `AdminDashboard`: RBAC-protected platform metrics and **Gemini AI Pipeline & Cost Observability** (`GET /api/admin/ai-metrics`).

2. **Backend API (`backend/app/`)**
   - **FastAPI** application initialized with SQLModel + Alembic (`alembic/versions/b9f4e21a8d10_ai_observability_cv_versions.py`).
   - **Centralized Gemini Gateway (`services/gemini_service.py`)**:
     - Single shared `google-genai` client across all AI features.
     - Model routing between `GEMINI_MODEL` and `GEMINI_FAST_MODEL`.
     - Persistent SHA-256 response cache (`AICacheEntry` table) and per-request telemetry (`AIOperationLog` recording `task_name`, `model_name`, `cache_hit`, `latency_ms`, `status`, token usage, and estimated USD cost).
     - Automatic deterministic fallbacks whenever Gemini is unconfigured, offline, or rate-limited.
   - **Universal Document Parsing (`services/cv_parser_service.py`)**:
     - Extracts normalized text from `.pdf` (`pypdf`), `.docx` (`python-docx`), `.md`, and `.txt` without fabricating missing contact details or employers.
   - **CV & Letter Generation (`services/cv_generator_service.py`)**:
     - Domain-agnostic skill bucketing and bilingual (`en` / `ka`) rendering into HTML, PDF (`WeasyPrint` / `ReportLab`), and Word (`.docx` via `python-docx`).
     - Supports live re-rendering from edited structured CV JSON via `render_cv_from_sections(...)`.
   - **Multi-User Isolation & Security (`services/auth_service.py`, routers)**:
     - Every user owns scoped `CandidateProfile`, `UserJobMatch`, `ApplicationTracker`, `SavedJob`, `SavedSearch`, `CandidateDocument`, `CVVersion`, and `SkillActionPlan` records.
     - OAuth flows bind user identity in signed JWT `state` tokens; admin routes enforce `get_current_admin`.

3. **Chrome Extension (`extension/`)**
   - **Manifest V3** Side Panel Copilot using least-privilege permissions (`activeTab`, `scripting`, `storage`, `sidePanel`) and dynamic `chrome.storage.sync` backend URL routing.
   - Extracts job metadata and multi-step form controls (`input`, `textarea`, `select`, `radio`, `[role="textbox"][contenteditable="true"]`) with a `350ms`-debounced `MutationObserver`.
   - Supports `.pdf`/`.docx`/`.md`/`.txt` profile sync, editable pre-fill answers, DataTransfer PDF attachment, and human-in-the-loop review before submission.
