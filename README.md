# TalentFlow AI

Multi-industry job discovery, grounded bilingual CV studio, application tracker, and Georgia remote B2B workspace built with **FastAPI**, **SQLModel / SQLAlchemy + Alembic**, **React 18 + TypeScript**, **Tailwind CSS**, **Gemini / OpenRouter**, and a **Chrome Extension (Manifest V3)**.

---

## What It Does

- **Candidate Profile Vault (Manual or Safe Import):** Every new account starts with an empty persisted draft profile. Build section-by-section manually or import `.pdf`, `.docx`, `.md`, or `.txt` files via preview + per-section `merge` / `replace` / `skip` controls (`POST /api/profile/import-preview`, `POST /api/profile/import-apply`).
- **Async Multi-Portal Job Discovery (12 Server-Side Portals + Extension):**
  - Server-side public boards: `jobs.ge`, `hr.ge`, `hr.gov.ge`, `headhunter.ge`, `remotive.com`, `himalayas.app`, `remoteok.com`, `djinni.co`, `dou.ua`, `justjoin.it`, `greenhouse.io`, `lever.co` via one durable async queue (`POST /api/jobs/scrape/async` + `GET /api/jobs/scrape/status/{task_id}`) with per-source health monitoring (`GET /api/jobs/sources/health`) and cross-portal deduplication.
  - LinkedIn & authenticated ATS portals are supported strictly via the user's own browser using the Chrome Extension (`extension/`). See [docs/DECISIONS.md](docs/DECISIONS.md).
- **Grounded Bilingual CV Studio (EN / KA):** Generates single-column ATS PDF (ReportLab, Sylfaen/DejaVu Unicode fonts), Word (`.docx`), and HTML CVs plus separate Cover Letters and Motivational Letters under `/api/cv-versions`, with automated `pypdf` ATS checks (`GET /api/cv-versions/{id}/ats-check`). Zero-fabrication rules are checked offline by the 30-case golden evaluation harness (`backend/evals/eval_runner.py`).
- **Application Kanban, Calendar & Email Drafts:** Stage tracking with immutable document snapshots, soft-delete + hard-purge (`DELETE /api/applications/{id}?hard=false|true`), RFC 5545 `.ics` / Google Calendar links, Gmail OAuth / SMTP / `.eml` draft packages, and vacancy-grounded STAR interview practice.
- **Georgia Remote B2B Hub (Feature-Flagged via `ENABLE_B2B_HUB`):** Compares Georgian Tax Code Article 90 (1% up to 500,000 GEL / 3% above threshold, informational only — not tax advice) against standard employment, live/fallback NBG FX rates, and a DST-aware Tbilisi (`UTC+4`) overlap matrix.
- **Hardened AI Gateway:** Structured Pydantic schemas with retry-once + fallback telemetry, versioned prompt templates (`backend/app/prompts/`), PII redaction, nonce-delimited untrusted input wrapping, per-user daily token budget, and optional explicit third-party AI consent (`docs/AI_SAFETY_AND_CONSENT.md`).

---

## Quickstart

### Prerequisites
- **Python 3.12+**
- **Node.js 20+** and **npm**

### 1. Configure Environment (Optional)
```bash
cp .env.example backend/.env
```
Key variables: `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY` (or `OPENROUTER_API_KEY`), `ENABLE_B2B_HUB=true`, `AI_DAILY_TOKEN_BUDGET_PER_USER=250000`, `AI_THIRD_PARTY_CONSENT_REQUIRED=false`, `GMAIL_USER` / `GMAIL_APP_PASSWORD`, `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

### 2. Start Backend (`:8000`)
```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Start Frontend (`:5173`)
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

### 4. Load Chrome Extension (Optional)
Open `chrome://extensions/`, enable **Developer mode**, click **Load unpacked**, and select `extension/`.

---

## Verification & CI Gates

```bash
# Backend lint, offline golden eval, tests & coverage floor (>=75%)
cd backend
pip install -r requirements-dev.txt
ruff check app tests evals
python -m evals.eval_runner
pytest tests ../tests/non_functional/test_security.py -q --cov=app --cov-fail-under=75

# Frontend lint, typecheck, unit tests & production build
cd ../frontend
npm run lint
npx tsc --noEmit
npm test
npm run build
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DECISIONS.md](docs/DECISIONS.md), and [docs/AI_SAFETY_AND_CONSENT.md](docs/AI_SAFETY_AND_CONSENT.md) for architecture details and trade-offs.
