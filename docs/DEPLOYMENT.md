# TalentFlow AI — Free & Low-Cost Production Deployment Guide

> **Critical Persistence Warning (SQLite vs. PostgreSQL)**:
> Free PaaS containers (Render Free Web Services, Railway trial containers without volumes, Fly.io ephemeral rootfs) **wipe local files on redeploy or spin-down**. Running default local `sqlite:///../data/job_assistant.db` on a stateless free dyno will **lose user accounts, uploaded CVs, and tracked applications** unless you attach a paid persistent disk OR switch `DATABASE_URL` to a managed free PostgreSQL database.

---

## 1. Free-Tier Architecture Comparison

| Layer | Option A (Zero-Cost Persistent DB) | Option B (Single-Platform Simple) | Notes |
|---|---|---|---|
| **Database** | **Neon Free Tier** (`512 MB` Postgres, 100 CU-hrs/mo) or **Supabase Free** (`500 MB` Postgres) | **Render Managed PostgreSQL** Free (`1 GB`, expires/requires renewal after 90 days) | Use `?sslmode=require` in `DATABASE_URL` |
| **Backend API** | **Render Free Web Service** (Docker / Python 3.11) — sleeps after 15 min idle (~30–50s cold start) | **Fly.io** (micro VM) or **Railway** (`$5` free trial credit, then usage-based) | Use Uvicorn + `alembic upgrade head` in start command |
| **Frontend SPA** | **Vercel Free** (`frontend/` root, Vite preset) | **Cloudflare Pages Free** (`npm run build`, output `dist/`) | Set `VITE_API_BASE_URL` to your deployed backend URL |
| **File Storage (Generated CVs)** | Store in `/tmp` or ephemeral disk for immediate download (persisted `structured_json` & `rendered_html` live in PostgreSQL `cv_versions` so PDFs/DOCX can always be regenerated cleanly!) | Persistent Volume (`/app/data`) on paid tier | `CVVersion` DB rows ensure editable CVs survive restarts even on stateless dynos |

---

## 2. Step-by-Step Deployment Checklist

### Step 1: Provision Free Managed PostgreSQL (Neon or Supabase)
1. Create a free PostgreSQL database on Neon or Supabase.
2. Copy the connection URI:
   ```text
   postgresql://USER:PASSWORD@HOST:5432/DB_NAME?sslmode=require
   ```
3. Run schema migrations locally or in your CI/release command:
   ```bash
   cd backend
   alembic upgrade head
   ```

### Step 2: Deploy FastAPI Backend (Render / Railway / Fly.io)
1. Point service root or Docker build to the repository root (`Dockerfile` builds backend dependencies including WeasyPrint/ReportLab/pypdf).
2. Configure environment variables:
   - `DATABASE_URL`: PostgreSQL URI from Step 1
   - `SECRET_KEY`: strong random 48+ byte URL-safe string
   - `ENVIRONMENT=production`
   - `ALLOWED_ORIGINS`: `https://your-app.vercel.app,chrome-extension://<YOUR_EXTENSION_ID>`
   - `GEMINI_API_KEY`: your Google AI Studio key (optional — deterministic fallback remains active if unset)
   - `GEMINI_MODEL=gemini-2.5-flash`
   - `GEMINI_FAST_MODEL=gemini-2.5-flash`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (if using Gmail OAuth)
3. Verify `/api/health` returns `{"status": "ok", ...}`.

### Step 3: Deploy Frontend SPA (Vercel or Cloudflare Pages)
1. Set Root Directory to `frontend`.
2. Build Command: `npm run build` | Output Directory: `dist`.
3. Set Build Environment Variable:
   - `VITE_API_BASE_URL=https://your-backend-service.onrender.com`
4. Open the deployed site, create/promote an admin via CLI (`python backend/scripts/create_admin.py --email ...`) if needed, upload a `.pdf`/`.docx`/`.md` CV, and confirm persistence across container restart.

### Step 4: Connect Chrome Extension to Production
1. Open the Chrome Extension Side Panel → click **⚙️ API**.
2. Enter your deployed backend URL (`https://your-backend-service.onrender.com`) and click **Save Backend URL**.
3. Sign in with email/password or click **Sync Session from Web Portal** while your Vercel/Pages tab is open.
