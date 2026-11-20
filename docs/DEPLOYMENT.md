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
1. Point service root or Docker build to the repository root (`Dockerfile` builds backend dependencies including ReportLab/pypdf/python-docx and Georgian/Latin Unicode fonts).
2. Configure environment variables:
   - `DATABASE_URL`: PostgreSQL URI from Step 1
   - `SECRET_KEY`: strong random 48+ byte URL-safe string
   - `ENCRYPTION_KEY`: dedicated Fernet base64 key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
   - `BLIND_INDEX_KEY`: dedicated independent HMAC secret (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) — **must remain separate from `ENCRYPTION_KEY`** so encryption key rotation never breaks email lookups
   - `ENVIRONMENT=production`
   - `ALLOWED_ORIGINS`: `https://your-app.vercel.app,chrome-extension://<YOUR_EXTENSION_ID>`
   - `REDIS_URL` (optional): shared Redis URI for distributed auth rate limiting (otherwise uses PostgreSQL `auth_rate_limits`)
   - `GEMINI_API_KEY`: your Google AI Studio key (optional — deterministic fallback remains active if unset)
   - `GEMINI_MODEL=gemini-3.6-flash`
   - `GEMINI_FAST_MODEL=gemini-3.5-flash-lite`
   - `GEMINI_TIMEOUT_MS=30000`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (if using Gmail OAuth)
3. Verify `/api/health` returns `{"status": "healthy", ...}`.

### Upgrading Existing Deployments (Blind-Index & Legacy CV Migration)
If upgrading an existing production database created before `BLIND_INDEX_KEY` separation (where `email_hash` was derived from the prior `ENCRYPTION_KEY`) or before per-user `generated/user_<id>/` CV isolation:
1. **Set transition secrets before deploy**:
   - Keep `ENCRYPTION_KEY` (or put the old value in `ENCRYPTION_KEY_PREVIOUS` if also rotating `ENCRYPTION_KEY`).
   - Set a new independent `BLIND_INDEX_KEY`.
   - Set `BLIND_INDEX_KEY_PREVIOUS=<your pre-upgrade ENCRYPTION_KEY>` (comma-separated if migrating across multiple historical keys).
2. **Deploy and verify**:
   - Application startup (`alembic upgrade head` + legacy CV migration) automatically moves unambiguous pre-existing files in `data/resumes/generated/` into `data/resumes/generated/user_<id>/` and updates `candidate_documents.storage_path`.
   - Existing users can log in and request OTPs immediately via `BLIND_INDEX_KEY_PREVIOUS`.
3. **Run full blind-index reindexing** while decryption keys remain configured:
   ```bash
   cd backend
   python -m app.services.crypto_service --reindex
   ```
   *(Optionally run legacy CV migration explicitly on a mounted volume via `python -m app.db.document_repository --migrate-legacy-cvs`.)*
4. **Finalize cleanup**:
   - Verify existing accounts can sign in cleanly, then remove `BLIND_INDEX_KEY_PREVIOUS` from your environment settings. Keep `ENCRYPTION_KEY_PREVIOUS` until encrypted PII columns have been re-encrypted under the new `ENCRYPTION_KEY`.

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
