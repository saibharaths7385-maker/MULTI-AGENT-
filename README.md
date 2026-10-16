# Synapse: multi-agent AI engineering workspace
Idea → **Planner** → human approval → **Engineer** → **Tester** → real pytest run in a sandbox → auto-fix loop → **Reviewer** → downloadable project + report.
Everything in the UI (status, logs, test output, files) comes from real execution. Projects persist in SQLite.

## Project layout
- `backend/` contains API routes, authentication, settings, database access, and agent orchestration.
- `frontend/templates/` contains the sign-in and workspace pages.
- `frontend/assets/` contains the frontend CSS and JavaScript.
- `app.py` remains a compatibility entry point for `uvicorn app:app`.

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
pytest                      # parser, path safety, authentication, sandbox tests
```

Before starting, set `ADMIN_PASSWORD` and a long, random `AUTH_SECRET`. Login uses the configured
`ADMIN_USERNAME` (defaults to `admin`) and `ADMIN_PASSWORD`; registration is intentionally disabled.
Set your model provider and `LLM_API_KEY` as needed. Example PowerShell setup:
```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "choose-a-long-unique-password"
$env:AUTH_SECRET = (python -c "import secrets; print(secrets.token_urlsafe(48))")
$env:LLM_API_KEY = "your-provider-key"
uvicorn app:app --reload
```
The sign-in page is at http://localhost:8000. Set `COOKIE_SECURE=1` when serving over HTTPS.
Do not commit `.env` or real credentials.

## Real isolation
`docker build -f Dockerfile.sandbox -t synapse-sandbox .` then `SANDBOX=docker` (no network, 512MB, 1 CPU, pid limit).
Process mode strips secrets and sets rlimits but is NOT a security boundary.

## Deploy
Render/Railway: Dockerfile is included; set the auth and model environment variables. Enable
`COOKIE_SECURE=1` when HTTPS is active. Mount a disk at `DATA_DIR`.

## Roadmap
GitHub PR integration, model arena/cost budgets, multiple users and teams, LangGraph port,
JS/other-language sandboxes, benchmark suite.
