# Rent Manager (Bhaada)

A multi-owner rent management web app for Indian landlords, built to run entirely on free tiers.

**Live app:** https://bhaada-nu.vercel.app · **Contents:** [User guide](#user-guide-for-owners) · [Where to find things](#where-to-find-things) · [Services we use](#services-we-use-and-why) · [Local setup](#local-setup) · [Deployment](#free-deployment-step-by-step) · [Architecture](#architecture)

- **Frontend:** React + Vite + TypeScript + Tailwind + TanStack Query, mobile-first (`/frontend`)
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 (`/backend`)
- **Database:** PostgreSQL on Neon (production), SQLite (local)
- **Files:** Supabase Storage private bucket (production), `./uploads` (local)
- **Email:** Brevo HTTPS API in production (Render's free plan blocks SMTP); Gmail SMTP optional locally
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

## User guide (for owners)

The app runs in any browser, on phone or computer. Live: **https://bhaada-nu.vercel.app**

### First-time setup (about 5 minutes)
1. **Create account:** open the app, tap **Create account**, and enter your name, email and password.
2. **Settings:**
   - **Profile & UPI:** add your UPI ID (e.g. `name@okhdfcbank`). Every reminder includes a one-tap UPI pay link.
   - **Message language:** English or Hindi for reminders.
   - **Default house rules:** your rules for new properties. Tick *"Also replace the rules of all my existing properties"* to apply them everywhere.
   - **Message templates:** edit the reminder, overdue, increment and welcome texts. Placeholders: `{name}` `{amount}` `{month}` `{unit}` `{due_date}` `{upi_id}` `{owner_name}`.
   - **Email:** nothing to set up. Emails show **your name**, and tenant replies come to **your email**. Tap **Send me a test email** to check.
3. **Properties:** **+ Add property** (name, address, house rules), then **+ Unit** for each flat or room, with its default rent.

### Adding tenants
- **New tenant (recommended):** go to **Links → + Create registration link**, pick the property (and optionally the unit), then **Share on WhatsApp** or **Copy link**. The tenant opens it and fills in their details, uploads their Aadhaar or PAN, reads the house rules and gives consent. A link works once and expires after 7 days by default.
- **Approve:** the new tenant appears on **Home → Pending approvals**. Tap **Review**, check the ID with **View ID document**, fill in rent, deposit, agreement dates, due day and yearly increment %, then tap **Approve**. The tenant gets a welcome email with the house rules. **Reject** deletes their ID document immediately.
- **Tenant already living with you:** go to **Tenants → + Add tenant**. You can create a new flat or room from the Unit dropdown.
- **Many tenants at once:** go to **Tenants → Import Excel**, download the blank template, fill it in, upload it, match the columns, check the preview, then import.

### Collecting rent
- Each month's rent appears automatically on the tenant's **Rent ledger** and on **Payments**.
- **Mark as paid:** open the tenant (or **Payments**), tap **Mark as paid**, and enter the amount (partial is fine), date, mode (UPI / Cash / Bank / Other) and reference. A **PDF receipt** is created and emailed to the tenant.
- **WhatsApp reminder:** tap **Remind** on a tenant. WhatsApp opens with the message already written, and you tap Send. To go through everyone due, use **Home → Send all due reminders**: it moves tenant by tenant, and you choose **Sent ✓** or **Skip** for each.

### Day-to-day pages
| Page | What it's for |
|---|---|
| **Home** | Today's to-do list: approvals, due today, overdue, rent increases in the next 30 days, agreements ending soon |
| **Dashboard** | Money overview: this month's expected, collected and pending, the last 12 months, collection rate, deposits held, chart |
| **Tenants** | Search and filter; open a tenant for profile, ledger, rent history, reminder log and actions |
| **Payments** | Monthly ledger and payment history; Excel download |
| **Links** | Registration links (create, share, turn off) |

### Tenant actions (open a tenant)
- **Change rent:** a manual rent change; yearly increases continue from the new amount.
- **Renew:** extend the agreement end date.
- **Vacate:** enter the move-out date and deductions (a ₹3,000 maintenance charge is pre-filled). It calculates **deposit − pending rent − deductions** and creates a **settlement PDF**.
- **Delete ID documents / Erase personal data:** for former tenants. Erasing removes the name, phone, email, address, ID and documents, and keeps payment records without the person's identity (DPDP right to erasure).

### When reminders go out (automatic, every day at 8 AM IST)
Example: due day **5** for December rent, still unpaid.

| Date | Who gets it | What |
|---|---|---|
| Dec 2 | Tenant (email) | Reminder: rent due in 3 days, with UPI link |
| Dec 5 | Tenant (email) | Due today |
| Dec 8, 11, 14, … | Tenant (email) | Overdue, every 3 days until paid |
| 30 days before the agreement anniversary | Tenant (email) | Rent increase notice (old rent → new rent) |
| On the anniversary | n/a | The new rent applies automatically, and Rent history updates |
| 30 and 7 days before the agreement ends | You (email) | Agreement ending; use **Renew** |
| 90 days after move-out | n/a | ID documents deleted automatically |

- Emails go only to tenants who gave an email address. Reminders stop as soon as the month is paid.
- **WhatsApp reminders are never automatic.** You send them yourself with the Remind button.
- The first month's due date is the agreement start date if that's later than the due day.

## Where to find things

### As an owner (in the app)
| What | Where |
|---|---|
| Rent receipt PDF | Tenant → **Rent ledger** → **Receipt**, or **Payments → Payment history → Receipt** |
| Settlement PDF | Vacated tenant → **Deposit settlement → Settlement PDF** |
| Tenant's ID document / photo | Tenant → **Profile → View ID document** (link valid for 5 minutes) |
| All your data in Excel | **Payments → Download Excel** (Tenants, Payments, Rent History, Summary); **Saved copy** opens the auto-saved latest version |
| Reminders sent | Tenant → **Reminder log** |
| Rent changes | Tenant → **Rent history** |

### As admin / developer
**Database (Neon):** https://console.neon.tech → project **bhaada** → **Tables** (browse) or **SQL Editor** (query). Use read-only `SELECT`s here; make changes through the app so its rules and audit log apply.

```sql
-- Owners
SELECT id, name, email, upi_id, created_at FROM owners;

-- Tenants with property and unit
SELECT t.id, t.full_name, t.phone, t.status, p.name AS property, u.name AS unit,
       t.current_rent, t.due_day, t.agreement_start_date, t.agreement_end_date
FROM tenants t
LEFT JOIN properties p ON p.id = t.property_id
LEFT JOIN units u ON u.id = t.unit_id
ORDER BY t.id DESC;

-- This month: due vs paid
SELECT t.full_name, r.month, r.amount_due, r.amount_paid, r.status, r.due_date
FROM rent_entries r JOIN tenants t ON t.id = r.tenant_id
WHERE r.month = to_char(now(), 'YYYY-MM');

-- Latest payments
SELECT p.paid_on, t.full_name, p.amount, p.mode, p.reference, p.receipt_number
FROM payments p
JOIN rent_entries r ON r.id = p.rent_entry_id
JOIN tenants t ON t.id = r.tenant_id
ORDER BY p.id DESC LIMIT 20;

-- Emails / WhatsApp reminders (and failures)
SELECT sent_at, tenant_id, type, channel, status, error FROM reminder_logs ORDER BY id DESC LIMIT 30;

-- Audit trail
SELECT created_at, owner_id, action, entity, entity_id, details FROM audit_logs ORDER BY id DESC LIMIT 30;
```

Other tables: `properties`, `units`, `registration_links`, `rent_history`, `message_templates`. Aadhaar/PAN numbers are stored encrypted (`id_number_encrypted`); only the last 4 digits are readable.

**Files (Supabase):** https://supabase.com/dashboard → project **bhaada-storage** → **Storage → rent-private**:
```
owners/<owner id>/
  rent-data.xlsx                    auto-saved Excel
  receipts/RM<owner>-<yymm>-<n>.pdf rent receipts
  tenants/<tenant id>/
    id-xxxx.pdf|jpg|png             ID document
    photo-xxxx.jpg|png              photo (optional)
    settlement-xxxx.pdf             move-out settlement
```
These are real people's ID documents. Don't download or share them unnecessarily, and **never make the bucket public**.

**Logs and health:**
- **Render → rent-manager-api → Logs.** Every boot prints `Startup check: storage=supabase … -> ok` and `email=brevo configured=yes`. Errors show `rid=<ref>`, which matches the "(ref …)" a user sees.
- **Health:** `https://rent-manager-api-bw0s.onrender.com/api/health` returns `{"status":"ok"}`.
- **Daily job runs:** GitHub → **Actions → Daily rent jobs**.
- **Emails sent:** Brevo → **Transactional → Logs**.

### Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| First page load takes 30–60 s | Render free plan sleeps after 15 min idle (normal). The paid plan (~$7/month) removes this. |
| "File storage is not available (ref …)" | Most often the **Supabase free project was paused** (7 days without activity): open the Supabase dashboard and click **Restore project**. The daily job touches storage every day to prevent this, and its GitHub Actions run turns red (GitHub emails you) if storage is down. Otherwise check Render logs for that `rid` (wrong/expired `SUPABASE_SERVICE_KEY`). |
| Emails not arriving | Check the spam folder first. Then Brevo → Transactional → Logs. Startup check must show `email=brevo configured=yes`. Brevo free = 300 emails/day. |
| Registration link "not available" | It was used, expired or turned off. Create a new one under **Links**. |
| Daily job red in GitHub Actions | `API_URL` / `CRON_SECRET` secrets don't match Render, or Render was down. Re-run with **Run workflow**. |

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
python -m app.scripts.seed              # demo data: demo@rentmanager.in / demo12345
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
cd backend && pip install -r requirements-dev.txt
ruff check app tests     # lint, including security rules
pytest -q
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
| `EMAIL_BACKEND` | `smtp` (Gmail SMTP), `brevo` (HTTPS email API) or `console` (log only). **Render's free plan blocks SMTP ports, so use `brevo` there.** |
| `BREVO_API_KEY`, `EMAIL_SENDER_ADDRESS` | For `brevo`: API key (Brevo, then SMTP & API, then API keys) and a sender address verified in Brevo. Emails show the owner's name, and replies go to the owner. |
| `SYSTEM_GMAIL_ADDRESS`, `SYSTEM_GMAIL_APP_PASSWORD` | A system Gmail for password-reset emails, and for owner notifications when the owner has not connected Gmail. |
| `REGISTRATION_RATE_LIMIT` | Public registration submissions per IP per hour (default 10). |

Frontend: `VITE_API_URL` stays empty when `/api` is served from the same domain (the Vercel rewrite). Set it only if you call the API directly.

## How to create a Gmail App Password (optional, for `EMAIL_BACKEND=smtp`)

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
3. Copy the **Project URL** (project home page), then **Project Settings → API Keys → Secret keys** and copy the `sb_secret_…` key. Keep that key secret; it is only for the backend. (Legacy `service_role` keys also work but are being retired.)

### 2b. Email on Brevo
1. Sign up at https://www.brevo.com (free: 300 emails/day) and verify your phone.
2. **Settings → Senders, domains, IPs → Senders → Add sender** with the address emails come from, then confirm the email Brevo sends you.
3. **Settings → SMTP & API → API keys → Generate**: access **Restricted**, **Transactional email = All**, everything else **None**. Copy the `xkeysib-…` key (it's shown once).
4. Later, a custom domain (authenticated under **Domains**) improves inbox placement compared with a Gmail sender.

### 3. Backend on Render
1. Push this repo to GitHub.
2. On https://render.com choose **New → Blueprint** and select the repo. Render reads `render.yaml`.
3. Fill in the values marked `sync: false`: `DATABASE_URL` (Neon), `FRONTEND_URL` (your Vercel URL; set it after step 4 if needed), `FERNET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (the new `sb_secret_…` key), `BREVO_API_KEY`, `EMAIL_SENDER_ADDRESS`, `SYSTEM_GMAIL_ADDRESS`. Paste each value **without** trailing spaces or new lines.
4. Deploy. Each start runs `alembic upgrade head` and then uvicorn. Check `https://<service>.onrender.com/api/health`.
5. Copy the generated `CRON_SECRET` value from the Render dashboard.
6. Optional demo data: open the Render shell and run `python -m app.scripts.seed`.

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

- **WhatsApp:** only official click-to-chat links are used. `WhatsAppSender` in `app/integrations/whatsapp.py` is an interface. To add the WhatsApp Cloud API later, implement `send()` and return it from `get_sender()`; nothing else needs to change.
- **Excel import:** "Base Rent" is treated as the rent the tenant pays today. A blank template is in `templates/tenant-import-template.xlsx`, and owners can also download it from the app.
- **Scaling:** the rate limiter is in-memory, which is fine for a single Render instance. Move it to Redis before running more than one instance.

## Services we use (and why)

The app is split across seven free services. Each does one job.

```
 Owner / tenant browser
        │  https://bhaada-nu.vercel.app
        ▼
 ┌───────────────┐   /api/*    ┌────────────────────┐   SQL    ┌─────────────────┐
 │ VERCEL        │ ──────────▶ │ RENDER             │ ───────▶ │ NEON            │
 │ website (UI)  │  (proxied)  │ backend (FastAPI)  │          │ database        │
 └───────────────┘             └────────────────────┘          └─────────────────┘
                                  │            │
                         files    │            │  emails
                                  ▼            ▼
                       ┌─────────────────┐  ┌─────────────────┐
                       │ SUPABASE        │  │ BREVO           │
                       │ private storage │  │ email sending   │
                       └─────────────────┘  └─────────────────┘

 GITHUB ── code + tests on every push ── daily 8 AM job ──▶ RENDER /api/jobs/run-daily
 UPTIMEROBOT ── pings RENDER /api/health every 5 min (keeps it awake, emails if down)
```

| Service | Its job in this app | What it stores / does | Free plan limit | If it's down or the limit is hit |
|---|---|---|---|---|
| **Vercel** | Hosts the **website** people open | The built React app (pages, buttons, forms). Forwards `/api/*` to Render, so the browser sees one domain. | Hobby plan: free but **non-commercial** | Website won't open. No data is affected. |
| **Render** | Runs the **backend** (the "brain") | Business rules: login, rent maths, receipts, reminders, security checks. Stores **no data itself**. | 750 instance-hours/month, 0.1 CPU, 512 MB; sleeps after 15 min idle; **blocks SMTP email ports** | Login and everything else fails with "Request failed (502)". Data stays safe in Neon and Supabase. |
| **Neon** | The **database** | All records: owners, properties, units, tenants (ID numbers encrypted), rent entries, payments, rent history, reminder logs, audit log. | 0.5 GB storage; sleeps when idle (wakes in under 1 s) | Nothing loads or saves. |
| **Supabase** | **Private file storage** | Tenant ID documents and photos, receipt PDFs, settlement PDFs, auto-saved Excel. Files open only through 5-minute signed links. (Only Storage is used, not Supabase's database or auth.) | 1 GB; **project pauses after 7 days of no activity** (the daily job prevents this) | Uploads, receipts, settlement PDFs and Excel copy fail with "File storage is not available". Payments and emails still work, and receipts are still emailed. |
| **Brevo** | **Sends all emails** | Rent reminders, overdue notices, increment notices, welcome emails, receipts, registration alerts, password resets. Sends over HTTPS because Render blocks normal email ports. Emails show the owner's name, and replies go to the owner. | 300 emails/day | Emails stop. Each attempt is logged as FAILED and retried on the next daily run. |
| **GitHub** | **Code, safety checks, daily scheduler** | Private repo. On every push or PR: lint, 50+ tests, frontend build. **Daily rent jobs** workflow calls the backend once a day. Merging to `main` auto-deploys Render and Vercel. | Free for private repos | Code is safe. If Actions are down for a day, that day's reminders are sent on the next run. |
| **UptimeRobot** | **Keep-awake + outage alerts** | Visits `/api/health` every 5 min, so Render never sleeps and pages load instantly. Emails you only when the backend goes down or comes back up. | 50 monitors, 5-min interval | Render goes back to sleeping when idle: the first visit takes about 50 s, but nothing breaks. |

Also used, but not services you manage: a **Gmail address** (the verified sender in Brevo), **WhatsApp** (`wa.me` links that open WhatsApp with a ready message; the owner taps Send, and no API is involved), and **UPI** (`upi://pay` links in reminders that open any UPI app with the amount filled in).

### What happens in a typical day
1. **Every 5 minutes:** UptimeRobot pings Render, which keeps it awake.
2. **Once a day (scheduled 8 AM IST; GitHub may start it a few hours late):** GitHub Actions calls `/api/jobs/run-daily` on Render. Render then:
   - checks Supabase storage (keeps it active),
   - creates the month's rent entries and marks overdue ones in **Neon**,
   - applies yearly increments,
   - sends due, overdue, increment and expiry emails through **Brevo**,
   - deletes old ID documents and refreshes the Excel copy in **Supabase**.
3. **When an owner uses the app:** browser → **Vercel** (page) → **Render** (`/api/...`) → **Neon** (data) or **Supabase** (files) → **Brevo** (emails such as receipts).
4. **When you merge a PR:** **GitHub** runs the tests, then **Render** (backend) and **Vercel** (frontend) redeploy automatically.

### Where to manage each one
| Service | Dashboard | What you'd go there for |
|---|---|---|
| Vercel | https://vercel.com/dashboard → **bhaada** | Deployments, website URL, custom domain |
| Render | https://dashboard.render.com → **rent-manager-api** | **Logs** (look for `Startup check:`), **Environment** (all secrets and settings), Manual Deploy / restart |
| Neon | https://console.neon.tech → **bhaada** | **Tables** / **SQL Editor** to view data, connection string, backups (branches) |
| Supabase | https://supabase.com/dashboard → **bhaada-storage** | **Storage → rent-private** (files), **Restore project** if paused, API keys |
| Brevo | https://app.brevo.com | **Transactional → Logs** (delivered or bounced emails), senders, API keys, daily usage |
| GitHub | https://github.com/patilanirudh/bhaada | Code, **Pull requests**, **Actions** (daily job and test runs), **Settings → Secrets** (`API_URL`, `CRON_SECRET`) |
| UptimeRobot | https://dashboard.uptimerobot.com | Uptime history, alert email settings |

### Where each secret lives
| Setting | Lives in | Comes from |
|---|---|---|
| `DATABASE_URL` | Render → Environment | Neon → Connect (pooled connection string) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Render → Environment | Supabase → project URL, **API Keys → Secret key** (`sb_secret_…`) |
| `BREVO_API_KEY`, `EMAIL_SENDER_ADDRESS` | Render → Environment | Brevo → **SMTP & API → API keys** (restricted to Transactional email); verified sender |
| `FERNET_KEY` | Render → Environment (+ **your own backup**) | Generated once. **Never change it**, or encrypted ID numbers become unreadable. |
| `JWT_SECRET`, `CRON_SECRET` | Render → Environment | Generated by Render |
| `API_URL`, `CRON_SECRET` | GitHub → Settings → Secrets → Actions | Render URL; same `CRON_SECRET` as Render |
| `FRONTEND_URL` | Render → Environment | Your Vercel URL (`https://bhaada-nu.vercel.app`) |

Secrets are **never** committed to the repo (`.env` files are git-ignored). When pasting values into Render, make sure there are no trailing spaces or blank lines.

### When to upgrade (rough order as you grow)
| Upgrade | About | Why / when |
|---|---|---|
| Vercel Pro, or move the website to Cloudflare Pages / Netlify | $20/month, or free | **Before charging landlords** (Hobby is non-commercial) |
| Supabase Pro | $25/month | Past about 500–1,000 tenants with ID documents (1 GB fills up); also removes the 7-day pause |
| Render Starter | $7/month | Always on, 5× CPU, about 100–200 concurrent users with 2 workers; UptimeRobot no longer needed for keep-awake |
| Brevo Starter | about $9/month | More than 300 emails/day (about 2,000+ tenants with email) |
| Own domain (e.g. `bhaada.in`) | about ₹800/year | Professional URL; authenticated email domain in Brevo so emails don't land in spam |
| Neon Launch | $19/month | Only at large scale (0.5 GB holds 100,000+ tenants) |

## Architecture

```
Browser (React SPA)  ──/api──▶  FastAPI backend  ──▶  PostgreSQL (Neon)
  pages → api/endpoints.ts        api/routes  (HTTP only)       │
        → api/client.ts           services    (business rules)  ├──▶ Supabase Storage (private files)
                                  db          (models, scope)   ├──▶ Brevo email API (HTTPS)
                                  integrations / documents      └──▶ wa.me links (owner taps send)
GitHub Actions cron ──X-Cron-Secret──▶ POST /api/jobs/run-daily
```

**Backend layers** (`backend/app/`). Dependencies point downward only:

| Layer | Responsibility | May import |
|---|---|---|
| `api/routes/` | HTTP: parse/validate requests, auth, rate limits, call a service, shape the response | services, db, schemas |
| `services/` | Business rules: rent maths, tenant lifecycle, ledger, registration, reminders, daily job. Raises domain errors (`core/errors.py`) and never imports FastAPI | db, integrations, documents |
| `db/` | SQLAlchemy models, sessions, and `OwnerScope`, the owner-filtered data gateway | core |
| `integrations/` | External systems behind interfaces: `Storage` (local / Supabase), email (Brevo HTTPS or SMTP), `WhatsAppSender` | core |
| `documents/` | File formats with no DB access: PDF receipts and settlements, Excel export/template/parsing | utils |
| `core/` | Config (with production safety checks), security (bcrypt, JWT, Fernet), errors, logging, defaults | nothing app-specific |

**Frontend** (`frontend/src/`): `pages/` (screens) → `api/endpoints.ts` (typed functions; the only file that knows URLs) → `api/client.ts` (fetch, token refresh, errors). Shared UI is in `components/`, and formatting/validation helpers are in `lib/`.

### Security & privacy

- **Tenant isolation:** every owner table has `owner_id`, and all reads go through `OwnerScope`. Tests prove owner A can't read or change owner B's data.
- **Auth:** bcrypt passwords. Short-lived access token kept in memory. Refresh token in an httpOnly cookie, rotated on use and revoked on logout or password change. Login is rate-limited per IP **and** per account.
- **ID data:** Aadhaar/PAN numbers are encrypted with Fernet, and the UI and exports show only the last 4 digits. Documents are checked by real file type, stored in a private bucket, opened through 5-minute signed URLs, and every view is audited.
- **Data minimisation and retention:** ID documents are deleted on rejection and 90 days after move-out. Owners can **erase a former tenant's personal data** (DPDP right to erasure); payment records are kept without the person's identity. A privacy notice and consent checkbox appear on the registration form.
- **Hardening:** CORS limited to the app URL. CSP, HSTS, nosniff and frame-deny headers. Generic 500 responses with a request ID, with details only in server logs. Access logs record paths only, never query strings (which can carry signed tokens). Rate limit and honeypot on the public form.
- **Safe configuration:** in production the app **refuses to start** if secrets are weak or default, `FERNET_KEY` is missing, cookies aren't secure, or it's pointed at SQLite or local disk.
- **Supply chain:** pinned dependencies. CI runs `ruff` (including bandit security rules), `pytest`, the TypeScript type check and the build.

## Project layout

```
backend/
  app/
    main.py            app factory: middleware, error mapping, routers
    api/               deps.py (auth, scope) + routes/ (one module per resource)
    services/          tenants, ledger, registration, rent, jobs, excel, messages, templates, audit
    db/                models.py, session.py, scope.py (OwnerScope)
    integrations/      storage.py, email.py, whatsapp.py
    documents/         pdf.py, excel.py
    core/              config, security, errors, logging, defaults
    scripts/seed.py    demo data
  alembic/             migrations
  tests/               pytest suite (isolation, security, jobs, ledger, registration, rent, validators)
frontend/
  src/api/             client.ts (fetch + auth) and endpoints.ts (typed API functions)
  src/pages/           Home (action today), Dashboard (money), Tenants, TenantDetail, Payments,
                       Properties, Links, Settings, PublicRegister, WhatsAppQueue, ImportExcel, auth
render.yaml  frontend/vercel.json  .github/workflows/daily-jobs.yml
templates/tenant-import-template.xlsx
```
