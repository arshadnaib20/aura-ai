"""SQLite memory and audit log."""
import sqlite3
import time
from contextlib import contextmanager

from . import config

_CONN = None


def get_conn():
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
    return _CONN


@contextmanager
def cursor():
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with cursor() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                args TEXT,
                approved TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                task TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'email',
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT,
                action TEXT NOT NULL,
                detail TEXT,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                used INTEGER NOT NULL DEFAULT 0,
                ts REAL NOT NULL,
                expires REAL NOT NULL
            )"""
        )
    # migrate older users table if missing provider column
    try:
        with cursor() as c:
            cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
            if "provider" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN provider TEXT NOT NULL DEFAULT 'email'")
    except Exception:
        pass


# ---- client activity (who did what) ------------------------------------
def log_activity(user_id, email, action: str, detail: str = ""):
    with cursor() as c:
        c.execute(
            "INSERT INTO activity (user_id, email, action, detail, ts) VALUES (?,?,?,?,?)",
            (user_id, email, action, detail[:1500], time.time()),
        )


def list_activity(limit: int = 50) -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            """SELECT a.id, a.user_id, a.email, a.action, a.detail, a.ts
               FROM activity a ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def client_stats() -> list[dict]:
    """Per-client summary: signups, last seen, message count, god toggles."""
    with cursor() as c:
        rows = c.execute(
            """SELECT u.id, u.name, u.email, u.provider,
                      u.ts AS signed_up,
                      (SELECT COUNT(*) FROM activity a WHERE a.user_id=u.id) AS events,
                      (SELECT MAX(a.ts) FROM activity a WHERE a.user_id=u.id) AS last_seen,
                      (SELECT COUNT(*) FROM activity a WHERE a.user_id=u.id AND a.action='chat') AS chats,
                      (SELECT COUNT(*) FROM activity a WHERE a.user_id=u.id AND a.action='god') AS god_toggles
               FROM users u ORDER BY u.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---- users ---------------------------------------------------------------
def create_user(name: str, email: str, password_hash: str) -> int:
    with cursor() as c:
        c.execute(
            "INSERT INTO users (name, email, password_hash, ts) VALUES (?,?,?,?)",
            (name, email.lower(), password_hash, time.time()),
        )
        return c.lastrowid


def get_user_by_email(email: str):
    with cursor() as c:
        r = c.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email=?",
            (email.lower(),),
        ).fetchone()
    return dict(r) if r else None


def get_user_by_id(user_id: int):
    with cursor() as c:
        r = c.execute(
            "SELECT id, name, email FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(r) if r else None


# ---- password reset tokens ----------------------------------------------
def create_reset_token(user_id: int, token: str, ttl_hours: float = 24) -> None:
    with cursor() as c:
        c.execute(
            "DELETE FROM reset_tokens WHERE user_id=? OR expires<?",
            (user_id, time.time()),
        )
        c.execute(
            "INSERT INTO reset_tokens (user_id, token, used, ts, expires) VALUES (?,?,0,?,?)",
            (user_id, token, time.time(), time.time() + ttl_hours * 3600),
        )


def get_reset_token(token: str):
    with cursor() as c:
        r = c.execute(
            "SELECT id, user_id, used, expires FROM reset_tokens WHERE token=?",
            (token,),
        ).fetchone()
    return dict(r) if r else None


def consume_reset_token(token_id: int) -> None:
    with cursor() as c:
        c.execute("UPDATE reset_tokens SET used=1 WHERE id=?", (token_id,))


def set_password(user_id: int, password_hash: str) -> None:
    with cursor() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))


# ---- admin ---------------------------------------------------------------
def all_users() -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            """SELECT u.id, u.name, u.email, u.provider, u.ts AS signed_up,
                      (SELECT COUNT(*) FROM activity a WHERE a.user_id=u.id) AS events,
                      (SELECT MAX(a.ts) FROM activity a WHERE a.user_id=u.id) AS last_seen,
                      (SELECT COUNT(*) FROM activity a WHERE a.user_id=u.id AND a.action='chat') AS chats
               FROM users u ORDER BY u.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: int) -> None:
    with cursor() as c:
        c.execute("DELETE FROM activity WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM reset_tokens WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))


def full_backup() -> dict:
    """Everything the owner might want to keep — JSON-safe export."""
    with cursor() as c:
        users = [dict(r) for r in c.execute("SELECT * FROM users ORDER BY id").fetchall()]
        activity = [dict(r) for r in c.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 5000").fetchall()]
        messages = [dict(r) for r in c.execute("SELECT * FROM messages ORDER BY id").fetchall()]
        notes = [dict(r) for r in c.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 2000").fetchall()]
        audit = [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 2000").fetchall()]
        jobs = [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY id").fetchall()]
    return {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "users": users,
        "activity": activity,
        "messages": messages,
        "notes": notes,
        "audit": audit,
        "jobs": jobs,
    }


# ---- messages ------------------------------------------------------------
def save_message(role: str, content: str):
    with cursor() as c:
        c.execute(
            "INSERT INTO messages (role, content, ts) VALUES (?,?,?)",
            (role, content, time.time()),
        )


def load_messages(limit: int = 20) -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---- notes ---------------------------------------------------------------
def add_note(content: str):
    with cursor() as c:
        c.execute(
            "INSERT INTO notes (content, ts) VALUES (?,?)",
            (content, time.time()),
        )


def list_notes(limit: int = 50) -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT id, content, ts FROM notes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_notes(query: str, limit: int = 20) -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT id, content, ts FROM notes WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- audit ---------------------------------------------------------------
def log_audit(action: str, args: str = "", approved: str = "yes"):
    config.ensure_logs_dir()
    with cursor() as c:
        c.execute(
            "INSERT INTO audit (action, args, approved, ts) VALUES (?,?,?,?)",
            (action, args[:2000], approved, time.time()),
        )
    # also append to daily log file
    try:
        day = time.strftime("%Y-%m-%d")
        with open(config.LOGS_DIR / f"audit-{day}.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {approved}: {action} {args}\n")
    except Exception:
        pass


def load_audit(limit: int = 25) -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT action, args, approved, ts FROM audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- jobs ----------------------------------------------------------------
def add_job(time_str: str, task: str):
    with cursor() as c:
        c.execute(
            "INSERT INTO jobs (time, task, active, ts) VALUES (?,?,1,?)",
            (time_str, task, time.time()),
        )
        return c.lastrowid


def list_jobs() -> list[dict]:
    with cursor() as c:
        rows = c.execute(
            "SELECT id, time, task, active FROM jobs ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def deactivate_job(job_id: int):
    with cursor() as c:
        c.execute("UPDATE jobs SET active=0 WHERE id=?", (job_id,))
