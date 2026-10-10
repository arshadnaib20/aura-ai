"""Video Studio — generate and edit videos through a configurable video API.

This module talks to any OpenAI-compatible video endpoint (fal.ai, Replicate,
or a provider you configure). It is used by the web UI's "Video Studio" panel.

Environment (see nova/config.py):
  VIDEO_API_KEY  — API key for the video provider (required to enable the panel)
  VIDEO_API_BASE — base URL of the provider's OpenAI-compatible endpoint
  VIDEO_MODEL    — model id to use (provider-specific)
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

from .. import config

DEFAULT_BASE = "https://queue.fal.run"


def _enabled() -> bool:
    return bool(config.VIDEO_API_KEY)


def _base_url() -> str:
    return (config.VIDEO_API_BASE or DEFAULT_BASE).rstrip("/")


def _request(path: str, payload: dict, timeout: int | None = None) -> dict:
    url = f"{_base_url()}/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Key {config.VIDEO_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    timeout = timeout or config.VIDEO_TIMEOUT
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate(prompt: str, duration: int = 6, ratio: str = "16:9") -> dict:
    """Generate a video from a text prompt. Returns {ok, video_url?, error?}."""
    if not _enabled():
        return {"ok": False, "error": "Video Studio is not configured. Add VIDEO_API_KEY to .env"}
    if not prompt or not prompt.strip():
        return {"ok": False, "error": "A prompt is required."}
    try:
        payload = {
            "prompt": prompt.strip(),
            "duration": int(duration),
            "ratio": ratio,
        }
        if config.VIDEO_MODEL:
            payload["model"] = config.VIDEO_MODEL
        resp = _request("/fal-ai/veo3/generate", payload, timeout=config.VIDEO_TIMEOUT)
        video_url = _extract_video(resp)
        if not video_url:
            return {"ok": False, "error": f"Provider returned no video URL: {json.dumps(resp)[:300]}"}
        return {"ok": True, "video_url": video_url, "provider": "fal-ai"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"Video API HTTP {e.code}: {body}"}
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        return {"ok": False, "error": f"Video API error: {e}"}


def edit(prompt: str, video_url: str) -> dict:
    """Edit an existing video (by URL) with a text instruction."""
    if not _enabled():
        return {"ok": False, "error": "Video Studio is not configured. Add VIDEO_API_KEY to .env"}
    if not video_url or not video_url.strip():
        return {"ok": False, "error": "A source video URL is required."}
    if not prompt or not prompt.strip():
        return {"ok": False, "error": "An edit instruction is required."}
    try:
        payload = {
            "prompt": prompt.strip(),
            "input_video_url": video_url.strip(),
        }
        if config.VIDEO_MODEL:
            payload["model"] = config.VIDEO_MODEL
        resp = _request("/fal-ai/veo3/edit", payload, timeout=config.VIDEO_TIMEOUT)
        video_url_out = _extract_video(resp)
        if not video_url_out:
            return {"ok": False, "error": f"Provider returned no video URL: {json.dumps(resp)[:300]}"}
        return {"ok": True, "video_url": video_url_out, "provider": "fal-ai"}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"Video API HTTP {e.code}: {body}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Video API error: {e}"}


def _extract_video(resp: dict) -> str | None:
    """Pull a video URL out of a provider response (handles common shapes)."""
    if not isinstance(resp, dict):
        return None
    for key in ("video_url", "url", "output"):
        val = resp.get(key)
        if isinstance(val, str) and val.startswith(("http", "https")):
            return val
        if isinstance(val, dict):
            for sub in ("url", "video_url", "media_url"):
                s = val.get(sub)
                if isinstance(s, str) and s.startswith(("http", "https")):
                    return s
    data = resp.get("data")
    if isinstance(data, dict):
        for key in ("url", "video_url"):
            s = data.get(key)
            if isinstance(s, str) and s.startswith(("http", "https")):
                return s
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for key in ("url", "video_url"):
                s = first.get(key)
                if isinstance(s, str) and s.startswith(("http", "https")):
                    return s
    return None


def status() -> dict:
    """Report whether the Video Studio is configured (safe, no secrets)."""
    return {
        "enabled": _enabled(),
        "model": config.VIDEO_MODEL or "provider default",
        "timeout": config.VIDEO_TIMEOUT,
        "note": None if _enabled() else "Add VIDEO_API_KEY to .env to enable the panel.",
    }
