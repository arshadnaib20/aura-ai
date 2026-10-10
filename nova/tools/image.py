"""Image Studio — generate and edit images from a prompt.

Primary provider: Pollinations (free, no API key, no quota).
Fallback provider: Google Gemini (Imagen / image models) when a key exists.

Used by the web UI's "Image Studio" panel.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
import urllib.error

from .. import config

POLL_BASE = "https://image.pollinations.ai/prompt"


def _enabled() -> bool:
    # Always available via Pollinations; Gemini is an optional upgrade.
    return True


def _pollinations(prompt: str, width: int = 768, height: int = 768, image_url: str | None = None) -> dict:
    """Generate/edit via Pollinations. No key required. Returns data URI."""
    url = f"{POLL_BASE}/{urllib.parse.quote(prompt)}?width={width}&height={height}&nologo=true"
    if image_url:
        url += "&image=" + urllib.parse.quote(image_url)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 AuraAI"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if not raw:
        return {"ok": False, "error": "Provider returned an empty image."}
    mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    b64 = base64.b64encode(raw).decode("ascii")
    return {"ok": True, "image_data": f"data:{mime};base64,{b64}", "provider": "pollinations"}


def _gemini_generate(prompt: str, ratio: str = "1:1") -> dict:
    """Try Gemini image models (needs quota; usually limited on free tier)."""
    key = (config.ALT_API_KEY or "").strip()
    if not key:
        return {"ok": False, "error": "no gemini key"}
    model = "gemini-2.5-flash-image"
    aspect = {"1:1": "1:1", "16:9": "16:9", "9:16": "9:16", "4:3": "4:3", "3:4": "3:4"}.get(ratio, "1:1")
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"], "aspectRatio": aspect},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"Gemini HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "error": f"Gemini error: {e}"}
    cands = d.get("candidates") or []
    if not cands:
        msg = (d.get("error") or {}).get("message", "no candidates")
        return {"ok": False, "error": f"Gemini: {msg}"}
    for part in cands[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or {}
        if inline.get("data"):
            mime = inline.get("mimeType", "image/png")
            return {"ok": True, "image_data": f"data:{mime};base64,{inline['data']}", "provider": "gemini"}
    return {"ok": False, "error": "Gemini returned no image part."}


def generate(prompt: str, ratio: str = "1:1") -> dict:
    """Generate an image from a text prompt."""
    if not prompt or not prompt.strip():
        return {"ok": False, "error": "A prompt is required."}
    p = prompt.strip()
    # Prefer Gemini if configured (better quality); fall back to Pollinations on any failure.
    if config.ALT_API_KEY:
        g = _gemini_generate(p, ratio)
        if g.get("ok"):
            return g
    try:
        return _pollinations(p)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"Image API HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "error": f"Image API error: {e}"}


def edit(prompt: str, image_url: str) -> dict:
    """Edit an existing image (by URL) with a text instruction."""
    if not image_url or not image_url.strip():
        return {"ok": False, "error": "A source image URL is required."}
    if not prompt or not prompt.strip():
        return {"ok": False, "error": "An edit instruction is required."}
    try:
        return _pollinations(prompt.strip(), image_url=image_url.strip())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"Image API HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "error": f"Image API error: {e}"}


def status() -> dict:
    return {
        "enabled": True,
        "model": "Pollinations (free) + Gemini (when key/quota available)",
        "note": "Free image generation — no API key needed.",
    }
