"""Desktop app launcher — allowlist only, approval required."""
import shutil
import subprocess

from .. import config, approval


def open_app(name: str) -> str:
    key = name.strip().lower()
    if key not in config.ALLOWED_APPS:
        return f"App not in allowlist: {name}. Allowed: {', '.join(config.ALLOWED_APPS)}"
    exe = config.ALLOWED_APPS[key]
    if not approval.ask_approval(f"open app '{name}'", exe):
        return "Opening cancelled (not approved)."
    try:
        path = shutil.which(exe) or exe
        subprocess.Popen([path])
        return f"Opened {name}"
    except Exception as e:
        return f"Could not open {name}: {e}"


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": f"Open an allowlisted desktop app. Allowed: {', '.join(config.ALLOWED_APPS)}",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "App name from the allowlist"}},
            "required": ["name"],
        },
    },
}
