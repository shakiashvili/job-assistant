# TalentFlow AI — Autonomous Career Platform & Extension Copilot

Multi-user AI Job Seeker Platform combining FastAPI, SQLModel, Alembic, Gemini AI (with caching, routing, and telemetry), React/TypeScript/Tailwind CSS, Playwright form staging, and a Manifest V3 Chrome Extension Side Panel.

## Key Capabilities
- **Dashboard Home & Analytics (`GET /api/analytics/candidate`)**: Profile completeness meter, missing-field diagnostics (never fabricated), job tier breakdowns, pipeline conversion metrics, and upcoming interview alerts.
- **Universal CV Parsing (`.pdf`, `.docx`, `.md`, `.txt`)**: Parses resumes cleanly with `pypdf` and `python-docx` alongside structured Ground Truth editing.
- **Multi-Portal Discovery & Strict Qualification Gates**: Scans and scores vacancies with explicit experience caps, remote/on-site verification, posting dates, and transparent salary provenance (`Verified` / `AI Estimated` / `Not Listed`).
- **CV Studio & Dual Letter Generation**: Generates domain-agnostic ATS, Recruiter, and Job-Tailored `.docx` + `.pdf` + HTML editions with saved `CVVersion` snapshots, inline section editing + live re-rendering, and separate **Cover Letter** vs. **Motivational Letter** tabs.
- **Centralized Gemini Pipeline & Admin AI Observability**: Shared `gemini_service` with `GEMINI_MODEL` / `GEMINI_FAST_MODEL` routing, SHA-256 DB response caching, deterministic offline fallback, and Admin cost/latency telemetry (`GET /api/admin/ai-metrics`).
- **Human-in-the-Loop Chrome Extension (`extension/`)**: Side Panel copilot supporting `.pdf`/`.docx`/`.md` uploads, editable auto-fill answers, and DataTransfer PDF attachment without auto-submitting or bypassing CAPTCHAs.

---

## Local Quickstart

### 1. Environment Configuration
```bash
cp .env.example backend/.env
# Edit backend/.env with SECRET_KEY and optional GEMINI_API_KEY
```

### 2. Backend Setup & Migrations
```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

### 4. Promote an Admin User (Optional)
```bash
python backend/scripts/create_admin.py --email admin@example.com
```

### 5. Run Verification Suites
```bash
# Backend unit, isolation, security & persistence tests
cd backend && pytest tests -q

# Frontend TypeScript & Vite production build
cd frontend && npm run build
```

---

## Documentation
- [System Architecture](docs/ARCHITECTURE.md)
- [Free-Tier Hosting & Persistence Guide](docs/DEPLOYMENT.md)
- [Chrome Extension Copilot & CWS Guide](docs/EXTENSION.md)
