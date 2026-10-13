# Aura AI — Tech Stack

Aura AI's core is deliberately small: **Python** drives the agent, and
**HTML/CSS/JS** renders the UI. Everything else is optional and only worth
adding when a concrete need appears.

## Current stack

| Layer | Technology | Why |
|---|---|---|
| Agent brain / server | Python (Flask) | The LLM ecosystem (Groq, OpenAI SDK) is Python-first; free-tier friendly |
| Memory / audit | SQLite | Zero-config, file-based, perfect for a local agent |
| Web UI | HTML + CSS + JS | Any web UI is written in these; embedded directly in the Flask app |
| Browser tool | Playwright (Python) | Headless browser control, one `pip install` |
| Hosting | PythonAnywhere (WSGI) | Free tier, runs `nova/deploy_server.py` unchanged |

## Where other languages fit (and when to use them)

| Language | Role it could play | Use it when… |
|---|---|---|
| **JavaScript / Node.js** | Health checks, small scripts, tooling | You need a quick zero-install script that shares the repo's web stack |
| **TypeScript** | Typed frontend / dashboard | You build a real SPA and want type safety at the UI layer |
| **Go** | Single-binary CLIs, fast background workers | You need a tiny deployable binary or a hot path in file/browser work |
| **Rust** | Performance-critical tooling | Only if Go or Python measurably can't meet a real constraint |
| **Python (existing)** | Everything core | The default — keep the agent logic here |

## The main tradeoff

Rewriting a working, deployed app in another language costs weeks and adds
nothing visible to the user. The rule: **keep Python + HTML as the core, and
only introduce another language for a specific, measurable need** — a faster
tool, a native desktop/mobile client, or a genuinely richer web UI.

## Working examples

Ready-to-run demonstrations live in [`extras/`](extras/README.md):
Node.js health check, Go repo-stats CLI, and a TypeScript dashboard.
