"""File tools — sandboxed inside nova_workspace only."""
import os
from pathlib import Path

from .. import config

WORKSPACE = config.WORKSPACE


def _resolve(path: str) -> Path:
    """Resolve a path and make sure it stays inside the workspace."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    if not str(p).startswith(str(WORKSPACE)):
        raise PermissionError(f"Access denied: path outside nova_workspace -> {p}")
    return p


def list_files(path: str = ".") -> str:
    p = _resolve(path)
    if not p.exists():
        return f"Path does not exist: {p}"
    out = []
    for entry in sorted(os.listdir(p)):
        full = p / entry
        kind = "dir" if full.is_dir() else f"{full.stat().st_size}B"
        out.append(f"{entry}  [{kind}]")
    return "\n".join(out) if out else "(empty folder)"


def read_file(path: str) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"File not found: {p}"
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = f"(binary file, {p.stat().st_size} bytes — cannot show as text)"
    return text[:8000]


def write_file(path: str, content: str) -> str:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p}"


def delete_file(path: str) -> str:
    p = _resolve(path)
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    else:
        return f"Not found: {p}"
    return f"Deleted {p}"


def move_file(src: str, dst: str) -> str:
    sp = _resolve(src)
    dp = _resolve(dst)
    dp.parent.mkdir(parents=True, exist_ok=True)
    sp.rename(dp)
    return f"Moved {sp} -> {dp}"


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "List files and folders in the Nova workspace. Argument path defaults to workspace root.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside nova_workspace, or '.' for root"}
            },
        },
    },
}
