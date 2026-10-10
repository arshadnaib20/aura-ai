"""Nova configuration — loads .env and defines safety boundaries."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- Paths ---------------------------------------------------------------
_HOME = os.environ.get("AURA_HOME")
PROJECT_ROOT = Path(_HOME) if _HOME else Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = PROJECT_ROOT / "nova.db"
STOP_FILE = PROJECT_ROOT / "STOP"

# ---- Brain ---------------------------------------------------------------
API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "llama-3.1-8b-instant")
BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Fallback models tried in order when the primary brain is rate-limited (429)
# or fails. Different models have separate quotas, so chats keep working.
# Verified live 2026-10: gpt-oss-120b/20b, qwen3.8-27b, allam-2-7b are valid on Groq.
FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "FALLBACK_MODELS",
        "openai/gpt-oss-20b,qwen/qwen3.8-27b,allam-2-7b",
    ).split(",") if m.strip()
]
# Optional second provider (any OpenAI-compatible API). Leave empty to skip.
ALT_API_KEY = os.getenv("ALT_API_KEY", "").strip()
ALT_BASE_URL = os.getenv("ALT_BASE_URL", "").strip() or "https://generativelanguage.googleapis.com/v1beta/openai"
ALT_MODEL = os.getenv("ALT_MODEL", "").strip() or "gemini-flash-latest"
# Optional third provider (e.g. DeepSeek). Leave empty to skip.
ALT2_API_KEY = os.getenv("ALT2_API_KEY", "").strip()
ALT2_BASE_URL = os.getenv("ALT2_BASE_URL", "").strip() or "https://api.deepseek.com/v1"
ALT2_MODEL = os.getenv("ALT2_MODEL", "").strip() or "deepseek-chat"

# ---- Workspace sandbox ---------------------------------------------------
WORKSPACE = (PROJECT_ROOT / os.getenv("WORKSPACE", "./nova_workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---- Permission level ----------------------------------------------------
# 0 suggest only | 1 ask every action | 2 auto low-risk, ask risky | 3 auto within scope
PERMISSION_LEVEL = int(os.getenv("PERMISSION_LEVEL", "2"))

# ---- God Mode ------------------------------------------------------------
# When true, Nova auto-approves everything (runs at effective level 3).
# Everything is still written to the audit log.
GOD_MODE = os.getenv("GOD_MODE", "false").strip().lower() in ("1", "true", "yes", "on")

# ---- Apps allowlist (name -> executable) ---------------------------------
ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "chrome": "chrome.exe",
    # add more apps here, e.g. "vscode": r"C:\Users\Administrator\AppData\Local\Programs\Microsoft VS Code\Code.exe"
}

# ---- Domains -------------------------------------------------------------
# Empty = any domain allowed. Otherwise only listed domains are allowed.
_domains_raw = os.getenv("ALLOWED_DOMAINS", "").strip()
ALLOWED_DOMAINS = [d.strip().lower().lstrip("www.") for d in _domains_raw.split(",") if d.strip()]
ALLOW_ANY_DOMAIN = len(ALLOWED_DOMAINS) == 0

# ---- Browser -------------------------------------------------------------
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "1").strip() == "1"

# ---- Approval mode -------------------------------------------------------
# "cli" = terminal y/n prompts (default), "web" = approve/deny buttons in web UI
APPROVAL_MODE = os.getenv("APPROVAL_MODE", "cli").strip().lower()

# ---- Web (public deployment) ----------------------------------------------
WEB_SECRET = os.getenv("WEB_SECRET", "nova-local-secret-change-me")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip()

# ---- Owner / Admin --------------------------------------------------------
# This email gets full admin panel access. Everything is still audited.
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "arshadnaib20@gmail.com").strip().lower()

# ---- Video Studio ---------------------------------------------------------
# Optional. When VIDEO_API_KEY is set, the web UI unlocks the "Video Studio"
# panel: generate a video from a prompt, or edit an existing video by URL.
# Works with any OpenAI-compatible video endpoint (e.g. fal.ai, Replicate,
# or a provider you configure). Leave empty to keep the panel hidden.
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "").strip()
VIDEO_API_BASE = os.getenv("VIDEO_API_BASE", "").strip()
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "").strip()
VIDEO_TIMEOUT = int(os.getenv("VIDEO_TIMEOUT", "300"))

# ---- Mail (optional, used by "forgot password") ---------------------------
# If SMTP_HOST is set, reset links are emailed; otherwise the link is shown
# in the response (useful on free hosts without SMTP).
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER or "nova@localhost").strip()


def ensure_logs_dir() -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR
