# TalentFlow AI

Multi-industry job discovery, grounded bilingual CV studio, application tracker, and Georgia remote B2B workspace built with **FastAPI**, **SQLModel / SQLAlchemy + Alembic**, **React 18 + TypeScript**, **Tailwind CSS**, **Gemini / OpenRouter**, and a **Chrome Extension (Manifest V3)**.

---

## What It Does

- **Candidate Profile Vault (Manual or Safe Import):** Every new account starts with an empty persisted draft profile. Build section-by-section manually or import `.pdf`, `.docx`, `.md`, or `.txt` files via preview + per-section `merge` / `replace` / `skip` controls (`POST /api/profile/import-preview`, `POST /api/profile/import-apply`).
- **Async Multi-Portal Job Discovery (12 Server-Side Portals + Extension):**
  - Server-side public boards: `jobs.ge`, `hr.ge`, `hr.gov.ge`, `headhunter.ge`, `remotive.com`, `himalayas.app`, `remoteok.com`, `djinni.co`, `dou.ua`, `justjoin.it`, `greenhouse.io`, `lever.co` via one durable async queue (`POST /api/jobs/scrape/async` + `GET /api/jobs/scrape/status/{task_id}`) with per-source health monitoring (`GET /api/jobs/sources/health`), zero-result alerting, and cross-portal deduplication (`also_on_portals`).
  - **Explainable Match & Skill-Gap Action Plan:** Every discovery card and Chrome Extension panel surfaces exact gate diagnostics (`Seniority`, `Discipline`, `Language` from `matching/gates.py`), matched skills, and 1-click `△ <Skill> +Plan` buttons wired to `POST /api/action-plans/add-skill`.
  - **Daily 09:00 AM Job Digest Alerts (Email / Telegram Bot / In-App):** Evaluates **all suitable vacancies across Direct, Adjacent, and Public Sector tiers** (or optional Saved Searches only), reports exact **Match %**, **Mismatch/Gap %**, matched skills, and **missing skills**, tracks every delivered vacancy in `digest_delivery_logs` so jobs are **never resent**, appends a compact **yesterday reminder** for unapplied roles, automatically **hides & excludes vacancies past the Discovered phase** (`Applied`, `HR Screening`, `Technical Interview`, `Assessment`, `Offer`, `Rejected`) from both **Job Discovery** and **Email/Telegram digests** (matched by job ID or URL), and still sends a clear status notice when 0 new vacancies were found (`POST /api/saved-searches/send-digest`, `GET /api/saved-searches/digest-schedule`). Auto-runs daily at `09:00 Asia/Tbilisi` while the backend is running, or standalone via `python -m app.services.digest_scheduler` (Windows Task Scheduler / cron).
  - LinkedIn & authenticated ATS portals are supported strictly via the user's own browser using the Chrome Extension (`extension/`). See [docs/DECISIONS.md](docs/DECISIONS.md).
- **Chrome Extension Copilot (Manifest V3):**
  - Shared, unit-tested portal DOM extractors (`extension/shared/extractors.js`, tested in Vitest against `jobs.ge`, `hr.ge`, `headhunter.ge`, `linkedin.com`, and Greenhouse HTML fixtures).
  - **Duplicate-Application Warning Badge** (`GET /api/extension/check-url`) detecting exact URL or cross-portal `(company, title)` matches before you apply.
  - **1-Click "Open Gmail Draft & Mark Applied"** (`POST /api/extension/prepare-gmail-draft`) pre-filling recipient email, subject, cover letter, attaching the tailored `.pdf`/`.docx` CV in Gmail Drafts (or Gmail Compose fallback), and atomically marking the role `APPLIED` on the Kanban board.
  - Native `chrome.downloads` support for tailored `.pdf` and `.docx` CVs (`GET /api/extension/download-cv/{filename}`).
- **Grounded Bilingual CV Studio (EN / KA):** Generates single-column ATS PDF (ReportLab, Sylfaen/DejaVu Unicode fonts), Word (`.docx`), and HTML CVs plus separate Cover Letters and Motivational Letters under `/api/cv-versions`, with automated `pypdf` ATS checks (`GET /api/cv-versions/{id}/ats-check`). Zero-fabrication rules are checked offline by the 30-case golden evaluation harness (`backend/evals/eval_runner.py`).
- **Application Kanban, Human-Approved Gmail Reply Sync & Calendar:** Stage tracking with immutable document snapshots, soft-delete + hard-purge (`DELETE /api/applications/{id}?hard=false|true`), **Sync Gmail Replies** (EN/KA employer reply classifier suggesting Kanban stage moves with 1-click **Approve** / **Undo**, `POST /api/applications/gmail/sync-suggestions`), **`+5 day` Follow-Up Email Drafts** (`POST /api/applications/{id}/follow-up-draft`), RFC 5545 `.ics` / Google Calendar links, and vacancy-grounded STAR interview practice.
- **Georgia Remote B2B Hub (Feature-Flagged via `ENABLE_B2B_HUB`):** Compares Georgian Tax Code Article 90 (1% up to 500,000 GEL / 3% above threshold, informational only — not tax advice) against standard employment, live/fallback NBG FX rates, and a DST-aware Tbilisi (`UTC+4`) overlap matrix.
- **Hardened AI Gateway & Typed Contracts:** Structured Pydantic schemas with retry-once + fallback telemetry, versioned prompt templates (`backend/app/prompts/`), PII redaction, nonce-delimited untrusted input wrapping, per-user daily token budget, optional explicit third-party AI consent (`docs/AI_SAFETY_AND_CONSENT.md`), and OpenAPI-generated TypeScript types (`backend/scripts/generate_openapi_types.py` → `frontend/src/types/openapi.generated.d.ts`).

---

## Quickstart

### Prerequisites
- **Python 3.12+**
- **Node.js 20+** and **npm**

### 1. Configure Environment (Optional)
```bash
cp backend/.env.example backend/.env
```
Key variables in `backend/.env` (never commit `.env`):
- **Core / AI:** `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY` (or `OPENROUTER_API_KEY`), `ENABLE_B2B_HUB=true`, `AI_DAILY_TOKEN_BUDGET_PER_USER=250000`, `AI_THIRD_PARTY_CONSENT_REQUIRED=false`.
- **Gmail Drafts, Reply Sync & Digest Emails:** Enable 2-Step Verification + IMAP in Gmail, generate a 16-character [App Password](https://myaccount.google.com/apppasswords), and set:
  ```env
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=465
  GMAIL_USER=your.email@gmail.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ```
  *(Optional Google OAuth2 for multi-user Gmail & Calendar: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`.)*
- **Telegram Bot & Daily 09:00 AM Digest Scheduler:** Create a bot via `@BotFather`, send `/start` to your bot, get your Chat ID via `@userinfobot`, and set in `backend/.env`:
  ```env
  TELEGRAM_BOT_TOKEN=123456789:your_bot_token
  TELEGRAM_DEFAULT_CHAT_ID=your_numeric_chat_id
  DAILY_DIGEST_ENABLED=true
  DAILY_DIGEST_HOUR=9
  DAILY_DIGEST_MINUTE=0
  DAILY_DIGEST_TIMEZONE=Asia/Tbilisi
  ```
  *Note:* The built-in scheduler runs automatically whenever the backend server is up (and catches up once per day if started after `09:00`). To deliver digests on Windows even when the web app is closed, schedule `python -m app.services.digest_scheduler` (working directory: `backend/`) at `09:00` in **Windows Task Scheduler** (or a cloud cron job).

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
# Backend lint, typecheck, offline golden eval, tests & coverage floor (>=75%)
cd backend
pip install -r requirements-dev.txt
ruff check app tests evals
mypy app/services app/db
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
