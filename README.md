# PhD Supervision Tracker

A small web app for following up PhD students across their projects. Students start with one project and add more over time; each project is active, inactive (paused) or closed.

- **Students** write a free-text weekly log. A local LLM (via [Ollama](https://ollama.com)) structures it per project: progress, next steps, blockers, whether they need help, and momentum. They review the result and submit. Students also get an **AI assist** to plan their week, get feedback on a piece of text, or turn a stuck point into a clear question.
- **The supervisor** gets a dashboard with a traffic light for every student × project, a **"Needs attention"** queue with quick-reply boxes, an AI **weekly digest** with talking points, and **AI-drafted feedback** that they edit before sending.

The app is built for one supervisor and up to about ten students. It uses FastAPI, server-rendered templates with HTMX, and SQLite.

## Bring your own model

The app does not include or provide a language model. It talks to **your own Ollama server**, set with `OLLAMA_URL` in `.env` (default `http://localhost:11434`). All AI calls go only to that server, so with a local Ollama nothing leaves your machine.

1. Install Ollama and pull a model, for example a Gemma model: `ollama pull gemma4`. Any chat model that supports JSON output works; larger models give better summaries but are slower.
2. Put the exact name shown by `ollama list` in `OLLAMA_MODEL`.
3. Keep Ollama listening on `127.0.0.1` only (its default), so other people on your network cannot use it.

## Local development (Windows)

The project uses its own virtual environment in `.venv` (Python 3.11 or newer):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env            # then edit: SECRET_KEY, BASE_URL=http://localhost:8000, SECURE_COOKIES=false
.venv\Scripts\python -m scripts.seed_demo        # optional demo data (logins listed in scripts/seed_demo.py)
.venv\Scripts\python -m uvicorn app.main:app --reload
```

On macOS or Linux, use `python3 -m venv .venv` and `.venv/bin/...` instead.

Open http://localhost:8000. On an empty database you are asked to create the supervisor account first. Add students under **Students**; each student gets an invite link that you send them yourself (there is no email sending).

Run the tests with `.venv\Scripts\python -m pytest`. Check the Ollama connection and output quality with `.venv\Scripts\python -m scripts.llm_smoke`.

## Running it for your group on a Windows server

The app can run natively from `.venv` on the same Windows machine as Ollama.

- Settings: `.env` (secret key, base URL, model, `APP_HOST`/`APP_PORT`). Data: `data\app.db`. Log: `logs\server.log`.
- Start by hand: `powershell -ExecutionPolicy Bypass -File scripts\run_server.ps1`
- Auto-start without admin rights (runs under your account while you are signed in or disconnected, not after sign-out or reboot until you sign in again): `powershell -ExecutionPolicy Bypass -File scripts\install_autostart_user.ps1`
- Auto-start at boot as a background task (needs an administrator): `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1`
- To let other computers reach the app, an administrator must allow the app's port in the firewall. Restrict it to your own network.
- Restart after code changes: `Stop-ScheduledTask "PhD Tracker"; Start-ScheduledTask "PhD Tracker"`. Database migrations run on start.
- For HTTPS, put a reverse proxy (IIS or Caddy) with a certificate in front, then set `BASE_URL=https://…` and `SECURE_COOKIES=true`.

## Running it on Linux (Docker)

Prerequisites: Docker with the compose plugin, Ollama running on the same host with the model pulled (`ollama list`), a DNS name pointing at the server, and ports 80/443 open.

```bash
git clone <this repository> phd-tracker && cd phd-tracker
cp .env.example .env && nano .env                        # SECRET_KEY, BASE_URL, DOMAIN, OLLAMA_MODEL
mkdir -p data backups && sudo chown 1000:1000 data backups
docker compose up -d --build
```

Then open `https://<your domain>`, create the supervisor account, and add students under **Students**.

Notes:
- Ollama keeps listening on `127.0.0.1:11434` only. The app reaches it via host networking, and only Caddy listens publicly. Check from another machine that port 11434 on your server is **not** reachable.
- Database migrations run automatically on start.
- Without Docker: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then run `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers` behind Caddy or nginx, for example as a systemd service.

### Backups

`python -m scripts.backup` makes a consistent copy of the SQLite database in `./backups/` and keeps the last 30. The Windows install scripts schedule it daily at 02:00. On Linux:

```bash
# crontab -e : daily backup at 02:00
0 2 * * * cd /path/to/phd-tracker && docker compose exec -T app python -m scripts.backup
```

Copy backups off the server regularly.

## How it works

| Piece | Where |
|---|---|
| Traffic-light rules (red: help request or 2+ weeks without a log; amber: low momentum, overdue milestone or no progress in 3+ weeks) | `app/status.py` |
| All LLM prompts | `app/llm/prompts.py` |
| Ollama client (JSON-schema output, one retry on invalid JSON) | `app/llm/client.py` |
| Background AI jobs (extraction, digest, feedback, assist) | `app/llm/tasks.py` |
| Routes | `app/routers/` |

AI work runs in the background, and pages poll for the result. Work that was interrupted by a restart, or that failed because Ollama was down, is retried when the app starts. The supervisor can also retry a failed log from the dashboard.

Schema changes: edit `app/models.py`, then run `.venv\Scripts\alembic revision --autogenerate -m "describe change"`.
