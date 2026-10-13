# Aura

**Aura AI** — a local, audited, approval-gated AI agent for your laptop — now also **hosted live**.

**Try it now:** https://arshadnaib20.pythonanywhere.com — create an account, sign in, and chat. Full email sign-up/sign-in, forgot-password reset, client activity dashboard, and an owner-only admin panel (owner: arshadnaib20@gmail.com) with JSON backup export and self-upgrade.

```
You
 ├── CLI / Web UI / Voice
 └── Aura Agent Loop
        ├── Brain: Groq free API (or Ollama later)
        ├── Memory: SQLite
        ├── Audit Log: SQLite
        ├── Approval Gate
        └── Tools
             ├── Files (workspace only)
             ├── Notes
             ├── Browser (Playwright)
             ├── Apps (allowlist only)
             └── Scheduler
```

Everything risky goes through the Approval Gate.  
Everything Aura does is written to the Audit Log.  
Everything file-related stays inside `nova_workspace/`.

## Quick start

```bash
# 1. Get a free API key: https://console.groq.com  -> API Keys -> Create
#    Then either paste it into .env or:
setx GROQ_API_KEY "your_key_here"
#    Close and reopen your terminal.

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows

# 3. Install packages
pip install -r requirements.txt
playwright install chromium

# 4. Run Aura
python -m nova.ui.cli        # terminal
python -m nova.ui.web        # ChatGPT-style web UI on localhost:5173
```

## Live deployment (PythonAnywhere)

The hosted version runs the same code via the WSGI entry point `nova/deploy_server.py`.
Deployment notes: the server venv must match the web app's Python version, `.env` lives
in the project root (the web app's working directory), and the owner email in `.env`
(`OWNER_EMAIL`) is what unlocks the `/admin` panel.

## What Aura v1.0 can do

- Chat with you (Groq brain)
- Remember notes and conversations (SQLite)
- Read/write files inside `nova_workspace/`
- Open a browser (Playwright, headless by default) and do simple web jobs
- Open allowlisted desktop apps
- Ask approval before risky actions
- Log everything to the audit log
- Run on ~4GB RAM (brain is in the cloud; your laptop only runs Python + SQLite + optional browser)

Aura will **not** run fully offline with a smart local model, open any app outside the
allowlist, act without approval on risky steps, or bypass safety.

## CLI commands

```
/exit    quit
/notes   list saved notes
/audit   show recent audit log
/stop    create STOP file (kills scheduler/browser jobs)
/level N change permission level (0-3)
/help    show commands
```

## Permission levels

| Level | Behavior |
|---|---|
| 0 | Suggest only — never executes |
| 1 | Ask before every action |
| 2 | Auto for low-risk, ask for risky (default) |
| 3 | Auto within scope, daily review |

## Safety rules (kept)

- Only files inside `nova_workspace/`
- Only allowed domains and apps
- Approval before write, delete, click, type, send, pay, post
- No raw shell access
- Audit log for every action
- Kill switch: `/stop` or Ctrl+C (a `STOP` file in project root stops jobs)
- Back up `nova_workspace/` and `nova.db`

## Folder structure

```
aura-ai/
├── .gitignore
├── LICENSE                     # MIT
├── README.md
├── TECH-STACK.md               # stack + when to use other languages
├── index.html                  # landing page
├── nova-logo.png
├── requirements.txt
├── requirements-server.txt     # PythonAnywhere / Render free tier
├── extras/                     # multi-language utilities
│   ├── README.md
│   ├── node-healthcheck/       # Node.js health check
│   ├── go-repostats/           # Go repo-stats CLI
│   └── ts-dashboard/           # TypeScript dashboard
├── nova/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── agent.py
│   ├── approval.py
│   ├── deploy_server.py        # WSGI entry point for the hosted app
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── files.py
│   │   ├── notes.py
│   │   ├── browser.py
│   │   ├── apps.py
│   │   ├── image.py            # Image Studio
│   │   ├── video.py            # Video Studio
│   │   └── scheduler.py
│   └── ui/
│       ├── __init__.py
│       ├── cli.py
│       └── web.py              # Flask web UI (login, chat, admin)
```

Local runtime files kept out of git (see `.gitignore`): `.env`, `nova_workspace/`,
`logs/`, `nova.db`, `venv/`.

