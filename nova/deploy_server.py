"""Nova public server entry (PythonAnywhere / Render free tier).

Runs the same Flask app as nova.ui.web but binds to 0.0.0.0 so the host
can route public traffic to it. Browser/apps/scheduler tools degrade
gracefully (Playwright not installed on free hosts) — chat, notes,
files and the activity DB all work.

Set in .env:
    GROQ_API_KEY=...       (Groq brain key)
    WEB_SECRET=...         (long random string — signs login sessions)
    GOOGLE_CLIENT_ID=...   (optional — enables 'Sign in with Google')

For PythonAnywhere: point the WSGI file at `nova.deploy_server:app`.
"""
import os
from pathlib import Path

for _k in list(os.environ):
    if _k.startswith("DOUBAO_") and "PROXY" in _k.upper():
        del os.environ[_k]

from nova.ui import web  # noqa: F401  (import registers routes)
from nova import db  # noqa

db.init_db()  # ensure tables exist the moment the WSGI app loads

app = web.app

if __name__ == "__main__":
    db.init_db()
    port = int(os.getenv("PORT", "8000"))
    print(f"Nova public server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
