# TalentFlow AI — Georgia Local & Global Remote B2B Career Platform

TalentFlow AI is a full-stack, multi-industry job discovery, grounded CV/cover-letter studio, and remote B2B career workspace built with **FastAPI**, **SQLModel / SQLAlchemy + Alembic**, **React 18 + TypeScript**, **Tailwind CSS**, **Gemini / OpenRouter AI**, and a **Chrome Extension (Manifest V3)**.

Built for job seekers in **Georgia (Tbilisi, `UTC+4`)** and global remote professionals across **any profession** (IT/QA, Software Engineering, Finance & Accounting, Data Analytics, Marketing, Logistics, HR, Legal/Public Admin, Hospitality, Healthcare, Sales), TalentFlow combines live local portal discovery (**Jobs.ge**, **HR.ge**, **HeadHunter.ge**, **HR.gov.ge**) with international & remote B2B boards (**Remotive**, **Himalayas**, **RemoteOK**, **Djinni**, **DOU**, **JustJoin.it**, **Greenhouse**, **Lever**, **LinkedIn**), bilingual English / Georgian (`ქართული`, Sylfaen font) ATS CV & full 4-paragraph cover letter generation, Kanban tracking, Google Calendar / `.ics` scheduling, and Georgia B2B tax/timezone planning.

---

## Core Capabilities

### 1. Upload-First Universal Profile Engine & Dynamic Experience Bounds
- **Upload-First Gate (Zero Auto-Seeded Drafts)**: TalentFlow never seeds a hardcoded QA or sample draft profile and blocks live portal scraping until you upload your own `.pdf`, `.docx`, `.md`, or `.txt` CV / skills file (`POST /api/profile/upload-skills` or `POST /api/skills-md/upload`).
- **Clean Multi-Format Parser**: Handles both Markdown and PDF/DOCX text exports (including ALL-CAPS headers, Word bullets, wrapped lines, and pipe-separated spoken languages), strips YAML frontmatter and AI meta-prompt instructions, canonicalizes skill casing (`FastAPI`, `PostgreSQL`, `REST API`, `SDLC`, `STLC`), and cleanly separates university degrees from technical trainings/certifications.
- **Universal Person-Adaptive Experience Analyzer**: Dynamically computes target experience bounds and seniority ceilings from each candidate's real history (`Entry-Level / Intern` → `Junior` → `Junior–Mid` → `Mid-Level` → `Senior` → `Lead / Principal`) and passes them into both live scraper query parameters and vacancy matching gates.

### 2. Hiring-Grade Multi-Portal Discovery & True Public Sector Separation
- **13 Live Portals**: `jobs.ge`, `hr.ge`, `headhunter.ge`, `hr.gov.ge`, `djinni.co`, `dou.ua`, `justjoin.it`, `greenhouse.io`, `lever.co`, `linkedin.com`, `remotive.com`, `himalayas.app`, and `remoteok.com`.
- **Freshness-First Feed & Filtering**: Defaults to **Newest Posted** using extracted publication dates, with `Posted Within` recency filters, market filters (`Georgia Market`, `Remote B2B`, `Global Remote`), work-mode filters, tier tabs (`Direct`, `Adjacent`, `Public Sector`), and saved bookmarks.
- **Hiring-Perspective Matching**:
  - Enforces seniority & experience-years gates (including Georgian qualifiers such as `Junior QA` vs `Middle / Senior QA` and `2+` / `ორწლიანი`+ requirements), discipline guards, and spoken-language compatibility.
  - **True Public Sector vs. Private Internships**: `Public Sector` is reserved strictly for `hr.gov.ge` and verified Georgian state ministries/LEPLs (`სსიპ`, `ა(ა)იპ`, `სამინისტრო`, `მერია`); private traineeships/internships are tagged cleanly as `Entry-Level / Internship`.
- **Multi-User Isolation**: Every authenticated candidate receives isolated profile storage, `UserJobMatch` scores, and generated documents.

### 3. Top-1% Grounded Bilingual CVs (EN / KA) & Full Cover Letters
- **ATS-Verified CV Studio (`CVVariantManager`)**: Generates single-column ATS PDF (ReportLab), editable Word (`.docx`), and print-ready HTML in **English** or **Georgian (`ქართული` with Sylfaen OOXML/PDF font support)**, verified automatically with `pypdf` ATS parseability checks (`GET /api/cv-versions/{id}/ats-check`).
- **Full 4-Paragraph Cover Letters & Distinct Motivational Letters**: Produces recruiter-grade, zero-fabrication 3–4 paragraph Cover Letters (and distinct Motivational Letters) citing concrete verified achievements from multiple employers and connecting relevant academic training (e.g., Economics degrees for banking/fintech roles).
- **Direct Portal Workflow**: Cleanly links directly to the vacancy on its source portal or prepares an email application package — no brittle headless-browser form auto-submitter.

### 4. Kanban Pipeline, Google Calendar (`.ics` + 1-Click) & Integrations Health
- **Visual Kanban Pipeline (`ApplicationTracker`)**: Drag-and-drop stages (`Discovered → Applied → HR Screening → Technical Interview → Offer / Rejected`), CSV export, and AI Interview Copilot prep (`POST /api/applications/{id}/prepare-interview`).
- **Google Calendar & Universal `.ics` Invites**:
  - One-click **Add to Google Calendar** (writes via Google Calendar API when OAuth is connected, or opens a pre-filled `calendar.google.com` event immediately with zero setup).
  - Universal RFC 5545 **`.ics` Calendar Export** (`GET /api/applications/{id}/calendar.ics?kind=interview|followup`) with 60-minute and 15-minute reminders for **Interviews** and **+5-day Follow-Up Reminders** (Google Calendar, Apple Calendar, Outlook).
- **Real Email Dispatch & RFC 2822 `.eml` Transport**: Supports **Gmail OAuth 2.0**, **Gmail SMTP / IMAP Drafts**, and automatic downloadable **`.eml`** drafts with your tailored CV attached when mail credentials are not configured.
- **Dashboard Integrations & System Health Panel** (`GET /api/applications/integrations/status`): Live status for Uploaded Profile, Google Calendar (including a 1-click **Test Google Calendar** link), Email/Gmail transport, AI Engine, and SQLite/Alembic database integrity (`alembic_version`, `PRAGMA integrity_check`, and `PRAGMA foreign_key_check`).

### 5. Georgia Remote B2B Market Hub
- **Georgia 1% Small Business vs. 20%+2% Labor Net Calculator** (`POST /api/b2b/tax-calculator`): Compares monthly & annual net take-home pay in USD, EUR, and GEL under Georgian Tax Code Article 90 (1% up to 500,000 GEL cumulative calendar-year turnover / 3% above threshold) vs. standard employment.
- **Tbilisi `UTC+4` Timezone Overlap Matrix** (`GET /api/b2b/timezone-matrix`) & persistent B2B Contractor Readiness Checklist + Proposal Generator.

### 6. Chrome Extension (Manifest V3) & Accessibility (WCAG 2.1 AA)
- [`extension/`](./extension/manifest.json) extracts live DOM job postings across Georgian, European, and global ATS/remote portals in your already-authenticated browser session and syncs via JWT.
- High-contrast obsidian + emerald UI with full keyboard navigation (`Skip to main content`, `Escape`-closable `role="dialog"` modals, visible focus rings, and `prefers-reduced-motion`).

---

## Project Structure

```text
job-application-assistant/
├── backend/                  # FastAPI API, SQLModel models, scrapers, AI & CV services
│   ├── alembic/              # Alembic database schema migrations (head: a3c9d14e7b52)
│   ├── app/
│   │   ├── db/               # SQLModel ORM tables, encrypted PII columns & repositories
│   │   ├── routers/          # auth, ground_truth, audit, b2b, jobs, tracker, extension, admin
│   │   ├── schemas/          # Pydantic request/response contracts
│   │   └── services/         # CV/PDF/DOCX generator, matcher, Gemini/OpenRouter gateway, Gmail/Calendar
│   │       └── scrapers/     # jobs.ge, hr.ge, hr.gov.ge, headhunter.ge, djinni, dou, justjoin, ats, b2b
│   └── tests/                # Pytest backend functional, regression, migration & calendar suites
├── frontend/                 # React 18 + TypeScript + Vite + Tailwind CSS
│   └── src/components/       # DashboardHome, AuditPanel, DiscoveryFeed, B2BMarketHub, ApplicationTracker, CVVariantManager, ProfileVault
├── extension/                # Chrome Extension Manifest V3 (popup, background SW, content scripts)
├── tests/non_functional/     # Playwright + axe-core WCAG 2.1 AA, performance & security probes
└── docs/                     # Architecture, deployment, extension & quality audit guides
```

---

## Local Development Quickstart

### Prerequisites
- **Python 3.11+**
- **Node.js 20+** and **npm**

### 1. Environment Setup (Optional for Local Use)
Copy `.env.example` to `backend/.env` to enable live AI, SMTP, or Google OAuth integrations:
```bash
cp .env.example backend/.env
```
Key optional variables:
- `SECRET_KEY`: Random hex secret for JWT signing (deterministic local dev fallback used when unset)
- `GEMINI_API_KEY` / `OPENROUTER_API_KEY`: Enables live AI parsing, CV/cover-letter crafting, and interview prep (clean deterministic engine runs automatically when unset)
- `GMAIL_USER`, `GMAIL_APP_PASSWORD`: Enables Gmail SMTP send & IMAP drafts with CV attached
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`: Enables Google OAuth 2.0 Gmail & Calendar API sync (1-click Google Calendar links & `.ics` invites work out of the box without OAuth)

### 2. Run Database Migrations & Backend API (`:8000`)
```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Run the Frontend App (`:5173`)
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Production build:
```bash
cd frontend
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

### 4. Load the Chrome Extension
1. Open Chrome → `chrome://extensions/`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension/` directory.

---

## Testing & Verification

### Backend Unit, Regression, Migration & Security Tests
```bash
cd backend
pytest tests ../tests/non_functional/test_security.py -q --tb=short
```

### Frontend TypeScript, Unit & Production Build Checks
```bash
cd frontend
npx tsc --noEmit
npx vitest run
npm run build
```

### Accessibility (WCAG 2.1 AA) & Performance Tests
With both backend (`:8000`) and frontend (`:5173`) running:
```bash
cd backend
pytest ../tests/non_functional/test_a11y_and_perf.py -v
```
