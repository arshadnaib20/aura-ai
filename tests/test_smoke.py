"""Smoke tests for the Aura AI web app.

Run with:  pytest tests -v
No API keys or network needed — the app must start and serve pages using
its built-in defaults.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_config_paths_stay_inside_project():
    from nova import config

    assert config.PROJECT_ROOT.exists()
    assert str(config.PROJECT_ROOT) in str(config.DB_PATH)
    assert str(config.PROJECT_ROOT) in str(config.WORKSPACE)


def test_web_app_serves_pages():
    from nova.ui import web

    client = web.app.test_client()
    for path in ("/", "/login", "/chat"):
        resp = client.get(path)
        assert resp.status_code < 500, f"GET {path} returned {resp.status_code}"


def test_auth_api_does_not_crash():
    from nova.ui import web

    client = web.app.test_client()
    resp = client.get("/api/me")
    assert resp.status_code < 500, f"GET /api/me returned {resp.status_code}"
