"""Browser tools — Playwright. Domains checked against config allowlist."""
from urllib.parse import urlparse

from .. import config, approval

_page = None
_browser = None
_pw = None


def _get_page():
    global _page, _browser, _pw
    if _page is not None:
        return _page
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright not installed. Run: pip install playwright && playwright install chromium")

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=config.BROWSER_HEADLESS)
    _page = _browser.new_page()
    return _page


def _check_domain(url: str) -> str:
    if config.ALLOW_ANY_DOMAIN:
        return "ok"
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in config.ALLOWED_DOMAINS):
        return "ok"
    return f"Domain not allowed: {host}. Allowed: {config.ALLOWED_DOMAINS}"


def browser_open(url: str) -> str:
    err = _check_domain(url)
    if err != "ok":
        return err
    page = _get_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1200)
    return f"Opened {page.url} — title: {page.title()}"


def browser_get_text(selector: str = "body") -> str:
    page = _get_page()
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=8000)
        return el.inner_text()[:3000]
    except Exception as e:
        return f"Could not read '{selector}': {e}"


def browser_click(selector: str) -> str:
    page = _get_page()
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=8000)
        el.click()
        page.wait_for_timeout(800)
        return f"Clicked {selector}"
    except Exception as e:
        return f"Click failed: {e}"


def browser_type(selector: str, text: str) -> str:
    page = _get_page()
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=8000)
        el.fill(text)
        return f"Typed into {selector}"
    except Exception as e:
        return f"Type failed: {e}"


def browser_screenshot(path: str = "screenshot.png") -> str:
    from .files import _resolve
    p = _resolve(path)
    page = _get_page()
    page.screenshot(path=str(p), full_page=False)
    return f"Screenshot saved: {p}"


def browser_close() -> str:
    global _page, _browser, _pw
    try:
        if _page is not None:
            _page.close()
        if _browser is not None:
            _browser.close()
        if _pw is not None:
            _pw.stop()
    finally:
        _page = _browser = _pw = None
    return "Browser closed."


# ---- schemas -------------------------------------------------------------
TOOL_SCHEMA_OPEN = {
    "type": "function",
    "function": {
        "name": "browser_open",
        "description": "Open a URL in the browser and return page title. Domains checked against allowlist.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL, e.g. https://wikipedia.org"}},
            "required": ["url"],
        },
    },
}

TOOL_SCHEMA_GET_TEXT = {
    "type": "function",
    "function": {
        "name": "browser_get_text",
        "description": "Read visible text from the current page (CSS selector, default body).",
        "parameters": {
            "type": "object",
            "properties": {"selector": {"type": "string", "description": "CSS selector, e.g. 'h1' or '.main p'"}},
        },
    },
}
