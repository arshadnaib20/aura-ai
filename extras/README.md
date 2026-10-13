# extras — Aura AI utilities in other languages

The core of Aura AI is Python (the agent brain) + HTML/CSS/JS (the web UI).
This folder shows where other languages fit in, with small, dependency-free
utilities you can actually run.

| Folder | Language | What it does | How to run |
|---|---|---|---|
| `node-healthcheck/` | Node.js | Pings the live site + fetches repo info | `node healthcheck.mjs` |
| `go-repostats/` | Go | Prints repo stats from the GitHub API | `go run .` (or `go build -o repostats .`) |
| `ts-dashboard/` | TypeScript | Typed dashboard: repo stats + site latency | `npx tsc dashboard.ts && node dashboard.js` |

All utilities hit public APIs only (GitHub API, the live site) and need no
API keys. See `TECH-STACK.md` at the repo root for the full reasoning about
when to use each language.
