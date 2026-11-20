# TalentFlow AI — Production Deployment & Operations Guide

> **Critical Persistence Warning (Ephemeral Free Plans vs. Production Persistence)**:
> Free PaaS containers (Render Free Web Services, Railway trial containers without volumes, Fly.io ephemeral rootfs) **wipe local files on redeploy, restart, or 15-minute idle spin-down**, cannot attach persistent disks, and (on Render Free) **block outbound SMTP ports 25, 465, and 587**.
> **Do not launch public multi-user accounts on Render Free web services or Render Free PostgreSQL.** Use a persistent managed PostgreSQL database, persistent document storage (S3/Cloudflare R2 and/or a mounted persistent disk), and HTTPS API email delivery.

---

## 1. Hosting Architecture Comparison

| Layer | Recommended Production Setup | Budget / Staging Setup | Notes |
|---|---|---|---|
| **Database** | **Neon** / **Supabase** / **Render Paid PostgreSQL** with automated backups | Managed PostgreSQL (staging/disposable data only) | **Warning:** Render Free PostgreSQL expires after **30 days**, followed by a **14-day grace period** before permanent deletion — never use it for real user accounts. Use `?sslmode=require` in `DATABASE_URL`. |
| **Document Storage (Uploaded & Generated CVs)** | **Cloudflare R2 / AWS S3** (`S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`) | **Render Starter + Persistent Disk** (`/app/data`, configured in `render.yaml`) + automatic encrypted DB blob fallback (`candidate_documents.encrypted_content`) | When S3/R2 is configured, files persist under per-user object prefixes (`users/user_<id>/...`) for horizontal scaling. Without S3, encrypted document blobs persist in PostgreSQL and hydrate automatically on restart. |
| **Backend API** | **Render Starter Web Service** (`render.yaml`, persistent disk `/app/data`) / Fly.io / Railway | Single container (`SCRAPE_WORKER_MODE=embedded`) | `entrypoint.sh` runs `alembic upgrade head`. Readiness probe `/api/health` & `/api/health/ready` execute a live `SELECT 1` DB check (returning HTTP `503` if unreachable); `/api/health/live` checks process liveness. |
| **Background Scraping** | Dedicated Background Worker (`python -m app.services.scrape_worker` with `SCRAPE_WORKER_MODE=external`) | Embedded durable DB queue (`SCRAPE_WORKER_MODE=embedded`) with startup stale-task recovery, heartbeats, and execution timeouts | Interrupted `RUNNING` tasks left by restarts or crashes are automatically recovered (`QUEUED` up to `max_attempts`, then `FAILED`) so discovery never gets permanently stuck. |
| **Transactional OTP Email** | **Resend** (`RESEND_API_KEY`) or **SendGrid** (`SENDGRID_API_KEY`) + `EMAIL_FROM` over HTTPS (port 443) | Password-only launch (`OTP_EMAIL_ENABLED=false`) | Render Free blocks outbound SMTP ports **25, 465, and 587**; always prefer HTTPS email APIs in cloud deployments. |
| **Frontend SPA** | **Vercel** (`frontend/` root, Vite preset) | **Cloudflare Pages** (`npm run build`, output `dist/`) | Set `VITE_API_BASE_URL` to your deployed backend URL. |

---

## 2. Step-by-Step Deployment Checklist

### Step 1: Provision Persistent Managed PostgreSQL
1. Create a persistent PostgreSQL database with automated backups enabled (e.g., Neon, Supabase, or Render Paid PostgreSQL — **do not** use Render Free PostgreSQL, which expires after 30 days + 14-day grace period).
2. Copy the connection URI:
   ```text
   postgresql://USER:PASSWORD@HOST:5432/DB_NAME?sslmode=require
   ```
3. Run schema migrations locally or in your release command:
   ```bash
   cd backend
   alembic upgrade head
   ```

### Step 2: Configure Persistent Document Storage (Recommended: S3 / Cloudflare R2)
- **Preferred for multi-user scale (S3 / Cloudflare R2)**:
  - Create a private bucket with bucket versioning/backups enabled.
  - Configure `S3_BUCKET`, `S3_ENDPOINT_URL` (for R2/MinIO), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `S3_REGION`.
  - Uploaded and generated CVs are stored under isolated per-user keys (`talentflow/users/user_<id>/uploads/...` and `talentflow/users/user_<id>/generated/...`) and hydrated cleanly across restarts or multiple API instances.
- **Persistent Disk & Encrypted DB Blob Fallback**:
  - `render.yaml` provisions `plan: starter` with a persistent disk mounted at `/app/data`.
  - When `S3_BUCKET` is not set, TalentFlow automatically stores Fernet-encrypted document payloads in `candidate_documents.encrypted_content` (up to 10 MB per file), so files survive container restarts and are included in PostgreSQL / portable JSON backups.

### Step 3: Deploy FastAPI Backend (Render / Railway / Fly.io)
1. Point service root or Docker build to the repository root (`Dockerfile` builds backend dependencies including ReportLab/pypdf/python-docx and Georgian/Latin Unicode fonts).
2. Configure environment variables (preserve the exact same keys across restarts — never regenerate encryption or blind-index keys on redeploy):
   - `DATABASE_URL`: persistent PostgreSQL URI from Step 1
   - `SECRET_KEY`: strong random 48+ byte URL-safe string
   - `ENCRYPTION_KEY`: dedicated Fernet base64 key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
   - `BLIND_INDEX_KEY`: dedicated independent HMAC secret (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) — **must remain separate from `ENCRYPTION_KEY`** so encryption key rotation never breaks email lookups
   - `ENVIRONMENT=production`
   - `ENABLE_PLAYWRIGHT=false` (server-side Chromium disabled in cloud hosting; local autofill runs via the Chrome Extension)
   - `FRONTEND_URL`: actual deployed frontend origin (e.g. `https://your-app.vercel.app`)
   - `CORS_ORIGINS` / `ALLOWED_ORIGINS`: `https://your-app.vercel.app,chrome-extension://<YOUR_EXTENSION_ID>`
   - `RESEND_API_KEY` (or `SENDGRID_API_KEY`) + `EMAIL_FROM` for HTTPS OTP delivery, **or** `OTP_EMAIL_ENABLED=false` for password-only authentication
   - `REDIS_URL` (optional): shared Redis URI for distributed auth rate limiting (otherwise uses PostgreSQL `auth_rate_limits` with automatic expired-row cleanup)
   - `SCRAPE_WORKER_MODE=embedded` (or `external` when running a dedicated `python -m app.services.scrape_worker` service)
   - `GEMINI_API_KEY`: your Google AI Studio key (optional — deterministic fallback remains active if unset)
   - `GEMINI_MODEL=gemini-3.6-flash`, `GEMINI_FAST_MODEL=gemini-3.5-flash-lite`, `GEMINI_TIMEOUT_MS=30000`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (only if using Google OAuth)
3. Verify health & readiness endpoints:
   - `GET /api/health/live` returns `200 {"status": "alive"}`
   - `GET /api/health` and `GET /api/health/ready` execute `SELECT 1` and return `200 {"status": "healthy", "database_reachable": true, ...}` (or `503` if PostgreSQL is unreachable).

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

### Step 4: Deploy Frontend SPA (Vercel or Cloudflare Pages)
1. Set Root Directory to `frontend`.
2. Build Command: `npm run build` | Output Directory: `dist`.
3. Set Build Environment Variable:
   - `VITE_API_BASE_URL=https://your-backend-service.onrender.com`
4. Open the deployed site, verify registration, login, CV upload, CV generation/download/delete, cross-user isolation, and restart persistence.

### Step 5: Connect Chrome Extension to Production
1. Open the Chrome Extension Side Panel → click **⚙️ API**.
2. Enter your deployed backend URL (`https://your-backend-service.onrender.com`) and click **Save Backend URL**.
3. Sign in with email/password or click **Sync Session from Web Portal** while your Vercel/Pages tab is open.

### Step 6: Verify Backups & Restore Drill
1. Database records (and encrypted document blobs when `storage_backend=db_blob`) are backed up via managed PostgreSQL snapshots and `backup_service.py` portable JSON snapshots.
2. When using S3/Cloudflare R2 (`storage_backend=s3`), enable bucket versioning and lifecycle/cross-region backup rules on your object-storage bucket separately from PostgreSQL backups.
3. Periodically test restoring a backup into a staging database and confirming user login + document download succeed.
