# Sanjeevani Clinic workshop project

FastAPI demo with the original COVID toy-data screening and pretrained NLP pages, plus MySQL accounts, clinical appointments and a Groq-powered homepage assistant.

## Setup (Python 3.13)

1. In MySQL, create a database and a user with permissions for that database:

   ```sql
   CREATE DATABASE sanjeevani CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'clinic'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
   GRANT ALL PRIVILEGES ON sanjeevani.* TO 'clinic'@'localhost';
   ```

2. Run `uv sync` (or install `requirements.txt` in a Python 3.13 virtual environment). Supply `DATABASE_URL` and `GROQ_API_KEY` in a local `.env` file copied from `.env.example`. `clinic/database.py` loads this file automatically; values already exported in your shell take precedence. On PowerShell, for example:

   ```powershell
   $env:DATABASE_URL = "mysql+pymysql://clinic:choose-a-strong-password@localhost:3306/sanjeevani"
   $env:GROQ_API_KEY = "your-groq-key"
   uv run uvicorn main:app --reload
   ```

   If the password contains special URL characters, percent-encode it in `DATABASE_URL`. Keep the key and database URL out of Git. On HTTPS deployments set `COOKIE_SECURE=true` and configure the proxy to forward its HTTPS origin correctly. The application creates tables on startup; use migrations when evolving a populated database.

3. Sign up through `/signup`. The assistant is available from the homepage after login. Set up **real** doctors and schedules from the trusted server shell (never expose this command to patients):

   ```powershell
   uv run python -m clinic.manage add-doctor "Asha Sharma" Neurology
   uv run python -m clinic.manage add-doctor "Ravi Mehta" Gastroenterology
   uv run python -m clinic.manage add-slot 1 "2026-10-01T10:00:00+05:30" 30
   ```

   Supported specialties: General Medicine, Neurology, Orthopedics, Gastroenterology and Dermatology. Add each doctor and slot actually available at your clinic; the project ships with **no fabricated doctors or slots**. Patients select a live slot and explicitly confirm before it is booked. A cancellation endpoint exists at `POST /api/bookings/{id}/cancel` with the user's `X-CSRF-Token` from `/api/me`.

4. An authorized clinic operator can record **clinician-verified** treatment history, used when a returning patient says hi:

   ```powershell
   uv run python -m clinic.manage add-treatment mohit@example.com 2 "stomach ulcer" "Follow-up planned" --ongoing
   ```

   The patient's account must exist first. A symptom in chat or an image does not create a diagnosis or treatment record.

## Behavior and limits

- The chatbot requests general suggestions and specialty advice from Groq. It only offers slots fetched from MySQL; the model cannot create doctors, determine real availability, or book on the patient's behalf. Selection is confirmed by the patient. Times are stored in UTC and shown in the browser's local timezone.
- Photos are validated, sent to Groq only after explicit consent and **not persisted**. A model cannot confirm that a wound is minor; emergency signals suppress routine booking and advise urgent in-person care. You should still have a clinician review health advice before any real clinical deployment.
- Passwords use scrypt hashing; database backed sessions use opaque HTTP-only cookies and CSRF tokens. Chat text and patient-provided booking reasons are stored per account. Keep MySQL access restricted and define a retention policy before using real patient data.
- The COVID page is a demonstration trained on `notebook/data/covid_toy.csv`. Its prediction and score are not clinical evidence.
- Existing `/pretrained-nlp` functionality still requires NLTK data and the downloaded GloVe model; `nlp_pretrained/download_nltk_data.py` prepares the NLTK data.

## Structure

`clinic/models.py` holds tables; `clinic/service.py` handles schedules and bookings; `clinic/assistant.py` contains the Groq and triage boundaries; `clinic/routes.py` contains the account and API routes; `clinic/manage.py` provides trusted server-side clinic setup. `main.py` includes the router and renders the original pages.

## Secure 10-server MCP assistant (new feature)

The original Groq chatbot is **unchanged** on `/`. Its original files are saved in `docs/original_chatbot_backup.zip`. The new grounded, RBAC-protected chatbot is at **http://127.0.0.1:8000/newpage.html**.

1. Install dependencies: `uv sync` (Python 3.13). `fastmcp>=4.0.10` is already in `pyproject.toml`. The updated `requirements.txt` also includes it.
2. Copy `.env.example` to `.env` and insert your **real** `DATABASE_URL`, optionally your `GROQ_API_KEY` for the **original** chatbot, and **required** random `ADMIN_SESSION_SECRET` for administrator MCP login. Do **not** upload `.env`.
3. Generate your admin secret in PowerShell, then paste it into your **local** `.env`:
   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
4. Start the app using **one process**: `uv run uvicorn main:app --reload`. The `mcp_audit_events` table is created with the clinic tables. On your first visit to `/admin/login`, the admin table receives the new `role` column (existing accounts default to `admin`).
5. Patient: log in at `/login`, then open `/newpage.html`. Admin: create/update an account **without typing the password into PowerShell history**, then log in via `/admin/login`:
   ```powershell
   uv run python -m mcp_rbac.manage create-admin clinicadmin
   ```
6. **Local trusted administrator only**: if you need a Super Admin account, run:
   ```powershell
   uv run python -m mcp_rbac.manage promote-admin clinicadmin
   ```
   Log out and log in again. Only Super Admin may read MCP audit events or assign admin roles. The `system` role cannot log in from a browser.
7. For internal diagnostics, run from a trusted terminal:
   ```powershell
   uv run python -m mcp_rbac.manage integrity
   uv run python -m mcp_rbac.manage cleanup
   ```

Example user messages: **“Show my profile”**, **“Show my appointments”**, **“Available neurology slots”**, **“Book slot 7”** (requires explicit form confirmation). Empty database lookups return **NO**; connectivity errors return an error, not a fabricated answer.

See `docs/MCP_ARCHITECTURE.md` for the 10 server inventory, security controls, data flow, known production limitations and RBAC behavior. The old unsecured medical MCP demo is disabled; do not run it instead of the main application.
