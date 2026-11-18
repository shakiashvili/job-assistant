# TalentFlow AI — Georgia Local & Global Remote B2B Job Seeker Platform

TalentFlow AI is a full-stack job search, resume tailoring, and remote B2B contracting platform built with **FastAPI**, **SQLModel / SQLAlchemy**, **React 18 + TypeScript**, **Tailwind CSS**, **Gemini AI**, **Playwright**, and a **Chrome Extension (Manifest V3)**.

Designed specifically for job seekers in **Georgia (Tbilisi, `UTC+4`)** and global remote engineers, TalentFlow combines live local portal discovery (**Jobs.ge**, **HR.ge**, **HeadHunter.ge**, **HR.gov.ge**) with global remote B2B contract boards (**Remotive**, **Himalayas**, **RemoteOK**, **Djinni**, **DOU**, **JustJoin.it**, **Greenhouse**, **Lever**), bilingual English / Georgian (`ქართული`, Sylfaen font support) CV & cover letter generation, application tracking, and remote contractor financial/timezone planning.

---

## Core Capabilities

### 1. Live Multi-Portal Discovery & Per-User Match Isolation
- **Georgian & Regional Boards**: `jobs.ge`, `hr.ge`, `headhunter.ge`, `hr.gov.ge`, `djinni.co`, `dou.ua`, `justjoin.it`, `greenhouse.io`, `lever.co`, and `linkedin.com`.
- **Global Remote B2B Boards**: Live JSON integrations for **Remotive**, **Himalayas**, and **RemoteOK**, automatically classified for **Georgia eligibility** (`REMOTE_B2B`, `GE_LOCAL`, or `REGION_LOCKED` detection for strict "US-only" / country-restricted roles).
- **Multi-User Score Isolation**: Every authenticated candidate receives personalized match scores and statuses via `UserJobMatch` without overwriting shared `JobPosting` rows across accounts.
- **Filter Controls**: Filter by work mode (`Remote` / `Hybrid` / `On-Site`), `B2B Remote Contracts`, `Georgia Eligible`, portal source, match score tier, and saved bookmarks.

### 2. Georgia Remote B2B Market Hub
- **Georgia 1% Small Business vs. 20%+2% Labor Net Calculator** (`POST /api/b2b/tax-calculator`): Compares monthly & annual net take-home pay in USD, EUR, and GEL across Georgia's **Individual Entrepreneur Small Business Status (1% up to 500,000 GEL / 3% above threshold)** versus standard **20% Personal Income Tax + 2% Funded Pension** employment contracts.
- **Tbilisi `UTC+4` Timezone Overlap Matrix** (`GET /api/b2b/timezone-matrix`): Maps synchronous collaboration windows across London (`UTC+0`), Berlin/CET (`UTC+1`), Dubai (`UTC+4`), Tel Aviv (`UTC+2`), New York EST (`UTC-5`), and San Francisco PST (`UTC-8`).
- **B2B Contractor Readiness Checklist**: Interactive persistent tracker covering Georgian Revenue Service (`rs.ge`) IE & Small Business registration, TBC/BOG multi-currency SWIFT accounts, Wise/Payoneer USD/EUR rails, MSA + IP assignment templates, and W-8BEN tax forms.
- **B2B Client Proposal Generator** (`POST /api/b2b/proposal`): Drafts tailored direct-outreach proposals grounded in your verified skills in English or Georgian (`ქართული`).

### 3. Profile Vault, Grounded Bilingual CVs (EN / KA) & Cover Letters
- Upload `skills.md`, `.pdf`, or `.docx` resumes to extract structured skills, work history, academic degrees, and target roles (`POST /api/profile/upload-skills`).
- Generate ATS-friendly Word (`.docx`) and PDF CVs + tailored cover letters in **English** or **Georgian (`ქართული` with Sylfaen font support)** grounded strictly in verified candidate facts.
- Interactive Canvas & Version Manager (`CVVariantManager`) and Kanban Application Tracker (`Saved -> Applied -> Interviewing -> Offer / Rejected`) with drag-and-drop and Google Calendar interview scheduling helpers.

### 4. Real Email Dispatch & RFC 2822 `.eml` Transport
- Supports real **Gmail OAuth 2.0** drafts and direct **Gmail SMTP** dispatch with your tailored CV attached.
- When SMTP/OAuth credentials are not configured, TalentFlow generates a standard downloadable **RFC 2822 `.eml` file** (`status="needs_transport"`) with your CV attachment already bundled so you never receive false "sent" confirmations.

### 5. Chrome Extension (Manifest V3)
- Located under [`extension/`](./extension/manifest.json) with real-time DOM job extraction across Georgian, European, and global ATS/remote portals (`jobs.ge`, `hr.ge`, `remotive.com`, `himalayas.app`, `remoteok.com`, `greenhouse.io`, `lever.co`, `linkedin.com`, `djinni.co`, `justjoin.it`, etc.).
- Auto-fills portal application forms, syncs JWT auth seamlessly with your local or deployed backend URL (`chrome.storage.sync`), and pauses whenever CAPTCHAs are present for human completion.

### 6. Accessibility (WCAG 2.1 AA) & Human-Centered UX
- High-contrast obsidian surface palette paired with emerald & teal accents designed to keep job-search sessions calm and legible (`Plus Jakarta Sans`, `Inter`, `Noto Sans Georgian`, and `JetBrains Mono`).
- Full keyboard accessibility (`Skip to main content`, `Escape`-closable dialogs with `role="dialog"` / `aria-modal="true"`, visible emerald focus rings, accessible form labels, and `prefers-reduced-motion` support).

---

## Project Structure

```text
job-application-assistant/
├── backend/                  # FastAPI API, SQLModel models, scrapers, AI & PDF services
│   ├── alembic/              # Database schema migrations
│   ├── app/
│   │   ├── db/               # SQLModel ORM tables, encrypted PII columns & repositories
│   │   ├── routers/          # auth, ground_truth, audit, b2b, jobs, tracker, stage, extension, admin
│   │   ├── schemas/          # Pydantic request/response contracts
│   │   └── services/         # CV/PDF/DOCX generator, Gemini 3.x gateway, Gmail/SMTP, Playwright stager
│   │       └── scrapers/     # jobs.ge, hr.ge, hr.gov.ge, headhunter.ge, remotive, himalayas, remoteok, etc.
│   └── tests/                # Pytest backend functional, unit & Playwright form integration tests
├── frontend/                 # React 18 + TypeScript + Vite + Tailwind CSS
│   └── src/components/       # DashboardHome, AuditPanel, DiscoveryFeed, B2BMarketHub, Tracker, CVStudio
├── extension/                # Chrome Extension Manifest V3 (popup, background SW, content scripts)
├── tests/non_functional/     # Playwright + axe-core WCAG 2.1 AA, performance & security probes
└── docs/                     # Architecture, deployment, extension & quality audit guides
```

---

## Local Development Quickstart

### Prerequisites
- **Python 3.11+**
- **Node.js 20+** and **npm**
- **Playwright Chromium** (optional, for automated form staging and accessibility tests)

### 1. Environment Setup
Copy `.env.example` to `backend/.env` and configure your keys:
```bash
cp .env.example backend/.env
```
Key optional/required variables:
- `SECRET_KEY`: Random hex secret for JWT signing
- `GEMINI_API_KEY`: Enables Gemini-powered skill extraction, salary estimation, tailored CVs, and interview prep
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_APP_PASSWORD`: Enables real OTP/application email sending
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`: Enables real Gmail OAuth 2.0 & Calendar integration

### 2. Run the Backend API (`:8000`)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Run the Frontend App (`:5173`)
```bash
cd frontend
npm install
npm run dev
```
For a production preview build:
```bash
cd frontend
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

### 4. Load the Chrome Extension
1. Open Chrome -> `chrome://extensions/`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension/` directory.

---

## Testing & Verification

### Backend Unit & Integration Tests
```bash
cd backend
pytest tests -q --tb=short
```

### Accessibility (WCAG 2.1 AA), Mobile & Performance Tests
With both backend (`:8000`) and frontend (`:5173`) running:
```bash
pytest tests/non_functional/test_a11y_and_perf.py -v
```
