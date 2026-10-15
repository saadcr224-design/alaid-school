# Alaid School — Management Desk

Full-stack, responsive school management application with a Python API and automatically initialized SQLite database. Runs locally with SQLite or on Vercel with a durable PostgreSQL database. PostgreSQL support uses psycopg.

## Included

- Setup-key-protected first super admin account, login, logout and expiring server sessions.
- Admin and teacher accounts, account disabling, server-enforced permissions.
- Academic session creation and switching. Each session has independent students, families, fees, staff, salaries, expenses and attendance.
- Admissions and student editing with unique admission numbers per session.
- Family groups linking multiple siblings; combined sibling invoices and collection.
- Monthly fee generation with duplicate prevention; partial payments and carried outstanding balances; super-admin payment reversal.
- Printable fee statements and reports (browser Print → Save as PDF).
- Staff records, monthly salary payments with duplicate prevention.
- Student attendance by date, including saved status updates.
- Cash ledger, expenses, financial summaries, CSV exports and recent activity log.
- Responsive desktop/mobile interface, no sample students or hardcoded credentials.

## Start locally

Install Python 3.12 or newer. Clone this repository, then run:

```bash
export SETUP_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf '%s\n' "$SETUP_KEY"
python server.py
```

Windows PowerShell:

```powershell
$env:SETUP_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
Write-Output $env:SETUP_KEY
python server.py
```

Open http://localhost:8000. Enter the setup key and create the super admin with a password of 12 or more characters. There is no default password. After setup, the key cannot create additional accounts. Create a session, add family groups if needed, admit students, then generate fees for your chosen month.

The database is created at `data/school.db` automatically. No database account or external API key is required. `.env.example` documents variables; the server reads real environment variables and does not automatically load `.env` files.

## Deploy on Vercel (alaid-school.vercel.app)

The repository now includes a Python Function (`api/index.py`) and explicit `/api/*` routing. Vercel hosts the frontend and backend; a PostgreSQL provider stores the records permanently. SQLite is **never** used on Vercel, including `/tmp`.

1. In the **alaid-school** Vercel project, use **Settings → Git** to connect `saadcr224-design/alaid-school`, with **main** as the production branch. Leave automatic Git deployments enabled.
2. **Root Directory** must be the repository root (blank), not `public`. Framework is **Other**. `vercel.json` supplies the `public` output directory and API configuration. Remove conflicting dashboard build overrides.
3. Under **Storage**, connect a PostgreSQL database (Neon is supported). Connect it to this project for **Production**. Ensure the integration supplies `DATABASE_URL` or `POSTGRES_URL` using its pooled connection string. Keep the provider's SSL requirements in the URL. No database secrets belong in GitHub or browser code.
4. In **Settings → Environment Variables**, add a strong random `SETUP_KEY` for Production. Generate one locally using `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep this key private: it authorizes first-admin creation. HTTPS cookies are automatic on Vercel.
5. Redeploy the latest **main** commit after connecting the database or changing environment variables. The schema is created automatically on the first API request under a database lock. Existing data is preserved.
6. Visit the site and complete first-admin setup using your setup key. If a setup account already exists, sign in instead.

`/api/status` returns JSON when the backend is running. If the database URL is absent, it returns HTTP 503 with `DATABASE_NOT_CONFIGURED` and the UI shows instructions. A 404 means the deployed commit/root directory is still incorrect.

### GitHub first → Vercel automatically

Commit and push code changes to this repository's **main** branch. Vercel's native Git integration builds that commit and updates `https://alaid-school.vercel.app/` after a successful production deployment. Feature branches create previews. Environment variable changes require redeployment. Student/payment edits are database writes and intentionally do not create Git commits.

The Git integration must be enabled in the project; uploading source alone cannot turn it on. Confirm each deployment's source commit under Vercel Deployments. Deployment may fail if GitHub integration permissions or the commit author's Vercel team access are missing.

### Verification status

The prior deployment returned HTTP 404 at `/api/status`. API routing and PostgreSQL support are now included. Connecting the Production database and setting `SETUP_KEY` require project settings access. A successful static page deployment alone does not verify database connectivity. The SQLite file from an earlier local/Docker run is not automatically imported into PostgreSQL.

## Optional Docker deployment

For local-disk SQLite, run one server instance with a persistent volume. For PostgreSQL, supply `DATABASE_URL` and install `requirements.txt`. A Vercel deployment needs neither a Docker container nor a persistent filesystem.

Build and run on a Docker host:

```bash
docker build -t alaid-school .
docker volume create alaid-school-data
docker run -d --name alaid-school --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e SETUP_KEY="your-long-random-setup-key" \
  -e COOKIE_SECURE=1 \
  -v alaid-school-data:/data alaid-school
```

Place an HTTPS reverse proxy in front of port 8000. Preserve the original Host header, enforce request timeouts/body limits, and expose only HTTPS. The built-in HTTP server is a simple origin server; the proxy is required for internet deployment. For local Docker testing over HTTP use `COOKIE_SECURE=0`. Secure cookies will not work on plain HTTP.

Keep a single application instance attached to its persistent volume. On each code update, rebuild the image and recreate the container with the **same volume**. Runtime data stays outside GitHub. Database backups are your responsibility; use SQLite's backup API while running rather than copying only the `.db` file in WAL mode:

```python
import sqlite3
with sqlite3.connect('/data/school.db') as source, sqlite3.connect('/backup/school-backup.db') as target:
    source.backup(target)
```

Protect backups as sensitive school data, copy them off the host, and verify restores regularly.

## Permissions and accounting

- Super admin: all school operations, user management and payment reversal.
- Admin: student/family/staff records, sessions, fees, salaries, reports and expenses.
- Teacher: student names/class/admission number and attendance only; financial and contact data are omitted from the API response.

Money is stored as integer paisa. Payment batches are atomic and cannot exceed outstanding balances. Existing invoices preserve their original amounts when monthly fees change. Outstanding invoices remain visible across months; they are not duplicated into new invoices. New sessions start empty; automatic student promotion/dues transfer between sessions is not implemented. Attendance currently covers students. Payroll records full monthly payments, not tax calculations or partial salary installments. Reports are cash summaries, not a double-entry accounting system. PDF output uses the browser print dialog.

The schema initializes automatically. This first version does not provide password recovery, automated backups, bank payments, SMS/WhatsApp integration or offline synchronization. The current delete action is blocked for records referenced by invoices, attendance or salary history to preserve integrity.

## Checks

```bash
python -m unittest discover -s tests -v
python -m py_compile server.py
node --check public/app.js
```

The integration test exercises authentication, session isolation, teacher restrictions, duplicate invoices, partial payments, overpayment prevention, atomic rollback, payment reversal, attendance updates, duplicate salary prevention and persisted records. Browser visual testing has not been performed in the build environment.
