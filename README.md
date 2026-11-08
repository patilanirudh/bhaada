# Rent Manager (Bhaada)

A multi-owner rent management web app for Indian landlords, built to run entirely on free tiers.

- **Frontend:** React + Vite + TypeScript + Tailwind + TanStack Query, mobile-first (`/frontend`)
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 (`/backend`)
- **Database:** PostgreSQL on Neon (production), SQLite (local)
- **Files:** Supabase Storage private bucket (production), `./uploads` (local)
- **Email:** each owner's own Gmail via App Password
- **Daily jobs:** `POST /api/jobs/run-daily`, called by a GitHub Actions cron at 08:00 IST

## Features

- Owner accounts: register, log in, forgot/reset password, change password. Access token (15 min) + refresh token (7 days, httpOnly cookie).
- Properties and units, with house rules as rich text.
- **Tenant self-registration links**: copy the link or share it on WhatsApp. The tenant fills a public form, uploads their Aadhaar/PAN (checked by magic bytes, max 5 MB) and gives DPDP consent. The owner approves or rejects.
- **ID security**: ID numbers encrypted with Fernet, and only the last 4 digits are ever shown. Documents sit in a private bucket and open through 5-minute signed URLs. They are deleted when a tenant is rejected, and automatically 90 days after move-out.
- Rent ledger: monthly entries, overdue marking, full and partial payments, **PDF receipts** emailed to the tenant.
- Yearly increment: `base × (1 + %/100)^completed_years`, rounded to the nearest rupee. A notice goes out 30 days before; the new rent applies on the anniversary.
- **Email reminders** (automatic): 3 days before the due date, on the due date, then every 3 days while overdue. Each includes a UPI pay link.
- **WhatsApp reminders** (two taps, official `wa.me` links only): per-tenant buttons and a "Send all due reminders" queue. Every tap is logged.
- Editable English/Hindi message templates; agreement-expiry alerts; move-out settlement PDF.
- **Excel**: on-demand export (Tenants, Payments, Rent History, Summary), an auto-saved copy after every change, and import with column mapping and preview.
- Dashboard: cards, an "Action today" list with one-tap actions, and a 12-month chart.
- Every query is scoped by `owner_id`, and tests prove isolation between owners. Audit log, rate-limited public form with a honeypot, CORS lock-down and security headers.

## Local setup

Requirements: Python 3.11+ (tested on 3.13), Node 20+.

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env            # defaults work for local dev (SQLite, console email, local uploads)
alembic upgrade head
python -m app.seed              # demo data: demo@rentmanager.in / demo12345
uvicorn app.main:app --reload --port 8000
```

```bash
# Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

API docs (development only): http://localhost:8000/api/docs

To run the daily job by hand (add `?on=2026-12-01` to replay a date; this is ignored in production):

```bash
curl -X POST -H "X-Cron-Secret: change-me-too" http://localhost:8000/api/jobs/run-daily
```

With `EMAIL_BACKEND=console`, emails are printed to the backend log instead of being sent.

### Tests

```bash
cd backend && pytest -q
```

The tests cover rent calculation, increments (including leap years), Aadhaar Verhoeff/PAN validation, owner data isolation, link expiry and usage limits, honeypot and rate limit, daily-job idempotency and retry, payments and receipts, Excel export/import, and move-out settlement.

## Environment variables (backend)

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` or `production`. Production hides the API docs, needs `FERNET_KEY` and adds HSTS. |
| `DATABASE_URL` | SQLite locally; the Neon connection string in production (`postgresql://…?sslmode=require`). |
| `FRONTEND_URL` | The app's public URL. Used for CORS, registration links and links in emails. |
| `EXTRA_CORS_ORIGINS` | Optional extra allowed origins, comma separated. |
| `JWT_SECRET` | Signs access, refresh, reset and file tokens. Use a long random string. |
| `FERNET_KEY` | Encrypts Aadhaar/PAN numbers and Gmail App Passwords. **Back it up, and never change it after go-live**, or the encrypted data becomes unreadable. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CRON_SECRET` | Shared secret for `POST /api/jobs/run-daily` (the `X-Cron-Secret` header). |
| `COOKIE_SECURE` | `true` in production (HTTPS). |
| `COOKIE_SAMESITE` | `lax` when Vercel proxies `/api` (the default setup). `none` only if the browser calls the API cross-site. |
| `STORAGE_BACKEND` | `local` or `supabase`. |
| `LOCAL_UPLOAD_DIR` | Folder for the local backend. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET` | Supabase project URL, the **service_role** key (server only) and a **private** bucket name. |
| `EMAIL_BACKEND` | `smtp` (real Gmail) or `console` (log only). |
| `SYSTEM_GMAIL_ADDRESS`, `SYSTEM_GMAIL_APP_PASSWORD` | A system Gmail for password-reset emails, and for owner notifications when the owner has not connected Gmail. |
| `REGISTRATION_RATE_LIMIT` | Public registration submissions per IP per hour (default 10). |

Frontend: `VITE_API_URL` stays empty when `/api` is served from the same domain (the Vercel rewrite). Set it only if you call the API directly.

## How to create a Gmail App Password

1. Open https://myaccount.google.com/security and turn on **2-Step Verification**. App Passwords need it.
2. Open https://myaccount.google.com/apppasswords.
3. Enter a name such as "Rent Manager" and click **Create**.
4. Copy the 16-letter password. Owners paste it in **Settings → Gmail for reminders** and then tap **Send test email**. Use the same steps for the system account (`SYSTEM_GMAIL_*`).

Gmail allows about 500 emails per day per account. If a send fails, it is logged as FAILED and retried on the next daily run, and the job keeps going.

## Free deployment, step by step

### 1. Database on Neon
1. Create a free project at https://neon.tech (region: Singapore or Mumbai if offered).
2. Copy the connection string, e.g. `postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`. The app switches it to the psycopg3 driver automatically.

### 2. File storage on Supabase
1. Create a free project at https://supabase.com.
2. Go to **Storage → New bucket**, name it `rent-private`, and leave **Public** **unchecked**.
3. Go to **Project Settings → API** and copy the Project URL and the `service_role` key. Keep that key secret; it is only for the backend.

### 3. Backend on Render
1. Push this repo to GitHub.
2. On https://render.com choose **New → Blueprint** and select the repo. Render reads `render.yaml`.
3. Fill in the values marked `sync: false`: `DATABASE_URL` (Neon), `FRONTEND_URL` (your Vercel URL; set it after step 4 if needed), `FERNET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SYSTEM_GMAIL_ADDRESS`, `SYSTEM_GMAIL_APP_PASSWORD`.
4. Deploy. Each start runs `alembic upgrade head` and then uvicorn. Check `https://<service>.onrender.com/api/health`.
5. Copy the generated `CRON_SECRET` value from the Render dashboard.
6. Optional demo data: open the Render shell and run `python -m app.seed`.

> On the free tier the service sleeps after 15 minutes idle, so the first request takes about 30–60 seconds. The cron workflow wakes it up before running the jobs.

### 4. Frontend on Vercel
1. Edit `frontend/vercel.json` and replace `YOUR-RENDER-SERVICE` with your Render service name.
2. On https://vercel.com choose **Add New → Project**, import the repo and set **Root Directory** to `frontend`. Vercel detects Vite.
3. Deploy. The rewrite proxies `/api/*` to Render, so the browser sees one domain and the refresh cookie stays first-party.
4. Put the Vercel URL (e.g. `https://rent-manager.vercel.app`) into Render's `FRONTEND_URL` and redeploy the backend.

### 5. Daily jobs with GitHub Actions
1. In GitHub go to **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `API_URL`: `https://<service>.onrender.com` (no trailing slash)
   - `CRON_SECRET`: the value from Render
2. `.github/workflows/daily-jobs.yml` runs every day at 02:30 UTC (08:00 IST). Test it now with **Actions → Daily rent jobs → Run workflow**.
3. Note: GitHub can delay scheduled runs by a few minutes, and pauses them in repos with no activity for 60 days. Push a commit now and then, or re-enable the workflow.

The job is idempotent. Every email is recorded in `reminder_logs` with a dedupe key, so running it twice on the same day sends nothing new.

## What the daily job does

1. Applies yearly increments on agreement anniversaries and writes `rent_history`.
2. Creates each active tenant's next monthly rent entry (7 days before its due date).
3. Marks unpaid entries past their due date as OVERDUE.
4. Emails rent reminders: 3 days before, on the due date, then every 3 days while overdue. It stops once the entry is paid.
5. Emails increment notices 30 days before the anniversary.
6. Emails the owner 30 and 7 days before an agreement ends.
7. Deletes ID documents 90 days after move-out.
8. Refreshes the auto-saved Excel file.

## Maintenance notes

- **WhatsApp:** only official click-to-chat links are used. `WhatsAppSender` in `app/services/whatsapp.py` is an interface. To add the WhatsApp Cloud API later, implement `send()` and return it from `get_sender()`; nothing else needs to change.
- **Excel import:** "Base Rent" is treated as the rent the tenant pays today. A blank template is in `templates/tenant-import-template.xlsx`, and owners can also download it from the app.
- **Scaling:** the rate limiter is in-memory, which is fine for a single Render instance. Move it to Redis before running more than one instance.

## Project layout

```
backend/
  app/
    main.py            FastAPI app, CORS, security headers, signed local file route
    models.py          SQLAlchemy models (owner_id on every owner table)
    deps.py            Current owner + OwnerScope (owner-filtered queries)
    routers/           auth, settings, properties, links, public, tenants, rent, excel,
                       reminders, dashboard, jobs
    services/          rent maths, daily jobs, email, storage, excel, pdf, whatsapp, templates
    seed.py            demo data
  alembic/             migrations
  tests/               pytest suite
frontend/
  src/pages/           Dashboard, Tenants, TenantDetail, Payments, Properties, Links,
                       Settings, PublicRegister, WhatsAppQueue, ImportExcel, auth pages
render.yaml  frontend/vercel.json  .github/workflows/daily-jobs.yml
templates/tenant-import-template.xlsx
```
