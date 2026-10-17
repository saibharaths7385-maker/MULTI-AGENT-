# Synapse: multi-agent AI engineering workspace
Idea → **Planner** → human approval → **Engineer** → **Tester** → real pytest run in a sandbox → auto-fix loop → **Reviewer** → downloadable project + report.
Everything in the UI (status, logs, test output, files) comes from real execution. Projects persist in SQLite.

## Project layout
- `backend/` contains API routes, authentication, settings, database access, and agent orchestration.
- `frontend/templates/` contains the sign-in and workspace pages.
- `frontend/assets/` contains the frontend CSS and JavaScript, including six selectable workspace themes.
- `app.py` remains a compatibility entry point for `uvicorn app:app`.

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
pytest                      # parser, path safety, authentication, sandbox tests
```

Open http://localhost:8000. Anyone can create an account at `/register`; every person only sees their
own projects. There is no admin password to configure. `AUTH_SECRET` is optional: if unset, Synapse
creates one in `DATA_DIR` and reuses it. Set `LLM_API_KEY` (and optionally the other model settings).
Set `COOKIE_SECURE=1` when serving over HTTPS. Do not commit `.env` or real credentials.

## Forgot password email
`/forgot-password` emails a one-hour, single-use link. Configure ONE provider (see `.env.example`):
- **Brevo** (`BREVO_API_KEY` + `MAIL_FROM`): free, only needs a verified sender address, works on Render's free plan.
- **Resend** (`RESEND_API_KEY` + `MAIL_FROM`): needs a verified domain to email people other than yourself.
- **SMTP** (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`): Render's free plan blocks SMTP ports.

Without a provider, password-reset requests return a generic confirmation but no reset link is created.
This avoids exposing one-time reset credentials in server logs. Configure email delivery before offering
password recovery to users.
Reset links use `APP_URL` (or Render's `RENDER_EXTERNAL_URL`). Resetting a password signs that account out everywhere.

## Real isolation
`docker build -f Dockerfile.sandbox -t synapse-sandbox .` then `SANDBOX=docker` (no network, 512MB, 1 CPU, pid limit).
Process mode strips secrets and sets rlimits but is NOT a security boundary.

## Deploy
Render/Railway: Dockerfile is included; set the model and email variables and `COOKIE_SECURE=1`.
**Accounts and projects live in SQLite under `DATA_DIR`. Mount a persistent disk there**, otherwise
every redeploy on a free instance erases all accounts. Projects from older single-admin databases remain
unassigned during migration so the first public registrant cannot claim another user's existing work.
An operator must explicitly associate any legacy projects with the correct account before they appear
in the per-user workspace.

## Roadmap
GitHub PR integration, model arena/cost budgets, teams and shared projects, LangGraph port,
JS/other-language sandboxes, benchmark suite.
