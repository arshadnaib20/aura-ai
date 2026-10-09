"""Approval gate — every risky action passes through here and is audited.
Supports terminal (y/n) and web (Approve/Deny button via polling queue).
"""
import sys
import threading
import time
import uuid

from . import config, db

# Web approval queue: token -> {"action", "details", "decision", "created"}
WEB_APPROVALS = {}
_WEB_LOCK = threading.Lock()


def _effective_level() -> int:
    """Return the effective permission level (God Mode overrides to 3 = auto-approve)."""
    if config.GOD_MODE:
        return 3
    return config.PERMISSION_LEVEL


def ask_approval(action: str, details: str = "") -> bool:
    """Ask the user before a risky action. Returns True if approved.
    God Mode (GOD_MODE=true) auto-approves everything but keeps the audit log."""
    level = _effective_level()
    if level == 0:
        db.log_audit(action, details, "suggested")
        return False
    if level == 3:
        db.log_audit(action, details, "auto")
        return True

    try:
        prompt = f"\n[APPROVAL] {action}"
        if details:
            prompt += f" — {details}"
        prompt += " [y/N]: "
        answer = input(prompt).strip().lower()
        ok = answer in ("y", "yes", "approve")
    except (EOFError, KeyboardInterrupt):
        ok = False

    db.log_audit(action, details, "yes" if ok else "no")
    return ok


def ask_approval_noninteractive(action: str, details: str = "") -> bool:
    """Used when no human can answer (scheduler). Auto-deny risky actions."""
    db.log_audit(action, details, "denied(no-tty)")
    return False


# ---- web approval queue --------------------------------------------------
def ask_approval_web(action: str, details: str = "", timeout: int = 120) -> bool:
    """Queue an approval for the web UI and wait for the user's decision.
    Returns True (approved) / False (denied or timed out). God Mode auto-approves."""
    level = _effective_level()
    if level == 0:
        db.log_audit(action, details, "suggested")
        return False
    if level == 3:
        db.log_audit(action, details, "auto")
        return True

    token = uuid.uuid4().hex
    with _WEB_LOCK:
        WEB_APPROVALS[token] = {
            "action": action,
            "details": details,
            "decision": None,
            "created": time.time(),
        }

    # wait up to `timeout` seconds for the UI to decide
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _WEB_LOCK:
            entry = WEB_APPROVALS.get(token)
        if entry is not None and entry["decision"] is not None:
            ok = entry["decision"] == "approve"
            with _WEB_LOCK:
                WEB_APPROVALS.pop(token, None)
            db.log_audit(action, details, "yes(web)" if ok else "no(web)")
            return ok
        time.sleep(0.5)

    with _WEB_LOCK:
        WEB_APPROVALS.pop(token, None)
    db.log_audit(action, details, "timeout")
    return False


def web_pending() -> list[dict]:
    """List pending web approvals (for the UI to render)."""
    with _WEB_LOCK:
        return [
            {"token": t, "action": e["action"], "details": e["details"]}
            for t, e in WEB_APPROVALS.items()
            if e["decision"] is None
        ]


def web_decide(token: str, approve: bool) -> bool:
    """Record the user's decision for a pending approval."""
    with _WEB_LOCK:
        entry = WEB_APPROVALS.get(token)
        if entry is None:
            return False
        entry["decision"] = "approve" if approve else "deny"
        return True
