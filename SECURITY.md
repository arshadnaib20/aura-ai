# Security Policy

Aura AI is a local-first, approval-gated assistant. This document explains how
to report issues and what safety properties the project guarantees.

## Reporting a vulnerability

- **Do not open a public issue** for a security problem.
- Email the maintainer directly: **arshadnaib20@gmail.com**
- Include: affected version/commit, a minimal reproducer, and the impact.

We aim to acknowledge reports within 3 business days and to ship a fix as soon
as a patch is ready. Until a fix is released, please keep details private.

## What Aura AI protects

| Property | How it's enforced |
|---|---|
| Files stay sandboxed | All file tools operate inside `nova_workspace/` only; paths outside are rejected |
| No surprise actions | Every risky action (write, delete, click, type, send, pay, post) goes through the approval gate |
| Everything is auditable | Every action is written to the SQLite audit log |
| No raw shell | There is no shell/tool-execution interface; apps open from a strict allow-list |
| Web access is restricted | Browser tooling only visits allow-listed domains |
| Secrets stay local | `.env` (API keys, `WEB_SECRET`) is gitignored and never committed; the README warns users never to upload it |

## Deployment checklist

- Keep `.env` out of any archive/backup you share; on PythonAnywhere it lives
  in the web app's working directory and is not part of the repo.
- Treat `GROQ_API_KEY` and `WEB_SECRET` as secrets: rotate them if they leak.
- Back up `nova_workspace/` and `nova.db`; they contain user data.
- The `/admin` panel is owner-only (unlocked by `OWNER_EMAIL` in `.env`).

## Known scope limits

Aura does **not** run fully offline with a smart local model, open apps outside
the allow-list, act without approval on risky steps, or bypass the safety rules
above. If you find a way past any of them, please report it using the process
above.
