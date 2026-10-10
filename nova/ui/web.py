"""Nova web UI — premium ChatGPT-style interface with login/signup.
Local only. Run: python -m nova.ui.web  then open http://127.0.0.1:5173
"""
import os
import sys
import threading
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# strip sandbox proxies before anything network-y
for _k in list(os.environ):
    if _k.startswith("DOUBAO_") and "PROXY" in _k.upper():
        del os.environ[_k]

from flask import Flask, jsonify, request, session, redirect, send_file, send_from_directory, Response

from .. import config, db
from ..agent import NovaAgent
from .. import approval

os.environ["APPROVAL_MODE"] = "web"
config.APPROVAL_MODE = "web"

ROOT = Path(__file__).resolve().parent.parent.parent

app = Flask(__name__)
app.secret_key = config.WEB_SECRET

agent = NovaAgent()

GOOGLE_CLIENT_ID = config.GOOGLE_CLIENT_ID  # set in .env for Google sign-in


@app.route("/nova-logo.png")
def logo():
    p = ROOT / "nova-logo.png"
    if p.exists():
        return send_file(str(p), mimetype="image/png")
    return "", 404

# chat runs in a background thread so approvals can be answered via polling
_busy = threading.Lock()


def hash_pw(pw: str) -> str:
    import hashlib, secrets
    salt = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_pw(pw: str, stored: str) -> bool:
    import hashlib
    try:
        salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
        return h == calc
    except Exception:
        return False


def login_required(fn):
    def wrapper(*a, **kw):
        if not session.get("uid"):
            return redirect("/login")
        return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    return wrapper


def _me():
    return {"uid": session.get("uid"), "email": session.get("email"), "name": session.get("name")}


def _log(action, detail=""):
    """Record who did what — every auth, chat, approval and toggle."""
    try:
        m = _me()
        if m["uid"]:
            db.log_activity(m["uid"], m["email"], action, detail)
    except Exception:
        pass


def google_verify(id_token: str):
    """Verify a Google ID token via Google's tokeninfo endpoint (no secret needed)."""
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token)
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
        if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
            return None, "Token audience mismatch."
        if not data.get("email"):
            return None, "Google token has no email."
        return data, None
    except Exception as e:
        return None, f"Google verification failed: {e}"


def is_owner() -> bool:
    return (session.get("email") or "").strip().lower() == config.OWNER_EMAIL


def owner_required(fn):
    def wrapper(*a, **kw):
        if not session.get("uid"):
            return redirect("/login")
        if not is_owner():
            return jsonify({"ok": False, "error": "Admin access only."}), 403
        return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    return wrapper


def _send_reset_email(email: str, reset_url: str) -> bool:
    """Send reset link via SMTP if configured; returns True if sent."""
    if not config.SMTP_HOST:
        return False
    import smtplib
    from email.mime.text import MIMEText
    try:
        msg = MIMEText(
            "Hello,\n\nSomeone asked to reset the password for your Aura AI account "
            f"({email}). If that was you, open the link below within 24 hours:\n\n{reset_url}\n\n"
            "If you did not ask for this, you can ignore this email.\n\n— Aura AI",
            "plain",
            "utf-8",
        )
        msg["Subject"] = "Aura AI — reset your password"
        msg["From"] = config.MAIL_FROM
        msg["To"] = email
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception:
        return False


def _reset_link(token: str) -> str:
    base = (config.PUBLIC_URL or "http://127.0.0.1:5173").rstrip("/")
    return f"{base}/reset?token={token}"


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aura AI</title>
<link rel="icon" href="/nova-logo.png">
<style>
:root{--bg:#050505;--bg2:#0A0A0C;--bg3:#0C0C10;--gold:#C9A961;--gold2:#E5CD8E;--txt:#EDEAE2;--dim:#8A8678;--line:#1E1E22;--line2:#26262C;--ok:#5EC8A5;--no:#E06666}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;height:100vh;display:flex;overflow:hidden}
/* ===== Left sidebar ===== */
.side{width:270px;background:var(--bg2);border-right:1px solid var(--line);display:flex;flex-direction:column;flex-shrink:0}
.brand{display:flex;align-items:center;gap:10px;padding:16px 16px;border-bottom:1px solid var(--line)}
.brand img{width:34px;height:34px;border-radius:9px;object-fit:cover}
.brand h1{font-size:15px;letter-spacing:.18em;font-weight:700}
.brand small{display:block;color:var(--dim);font-size:10px;letter-spacing:.08em}
.navgrp{padding:12px 0;border-bottom:1px solid var(--line)}
.navitem{display:flex;align-items:center;gap:10px;padding:9px 16px;color:var(--dim);font-size:12.5px;cursor:pointer;transition:.15s;border:none;background:none;width:100%;text-align:left}
.navitem:hover{color:var(--gold);background:#101014}
.navitem.on{color:var(--gold);background:#101014;border-left:2px solid var(--gold)}
.navitem svg{flex:none;opacity:.85}
.newbtn{margin:12px;padding:11px;border-radius:11px;border:1px solid var(--line2);background:transparent;color:var(--txt);cursor:pointer;font-size:13px;transition:.2s;display:flex;align-items:center;justify-content:center;gap:8px}
.newbtn:hover{border-color:var(--gold);color:var(--gold)}
.hist{margin:8px 0;padding:0 10px;overflow-y:auto;flex:1}
.hist h4{font-size:10.5px;letter-spacing:.14em;color:var(--dim);padding:10px 8px 6px}
.hit{padding:9px 10px;border-radius:9px;cursor:pointer;font-size:12.5px;color:var(--dim);border:none;background:none;width:100%;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:.15s}
.hit:hover{background:#101014;color:var(--txt)}
.foot{padding:13px 16px;border-top:1px solid var(--line);font-size:11px;color:var(--dim);line-height:1.8;background:#08080A}
.foot .godrow{display:flex;align-items:center;justify-content:space-between;margin-top:9px}
.foot .user{display:flex;align-items:center;gap:9px;margin-bottom:8px}
.foot .user .av{width:30px;height:30px;border-radius:50%;background:var(--gold);color:#111;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px}
.foot .user b{font-size:12.5px;color:var(--txt);display:block;line-height:1.3}
.foot .user small{font-size:10.5px;color:var(--dim)}
/* ===== Center ===== */
.mid{flex:1;display:flex;flex-direction:column;min-width:0}
.top{padding:13px 22px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--dim);background:rgba(8,8,10,.7)}
.top b{color:var(--txt)}
.acc{display:flex;align-items:center;gap:10px}
a.logout{color:var(--dim);text-decoration:none;font-size:12px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;transition:.15s}
a.logout:hover{color:var(--no);border-color:#3A2A2A}
.chat{flex:1;overflow-y:auto;padding:26px 10px;display:flex;flex-direction:column;gap:20px}
.wrap{max-width:780px;margin:0 auto;width:100%;display:flex;flex-direction:column;gap:20px}
.m{display:flex;gap:14px;align-items:flex-start}
.m .ic{width:30px;height:30px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.u .ic{background:#1E1E22;color:var(--gold)}
.n .ic{background:linear-gradient(135deg,#E5CD8E,#C9A961);color:#111}
.m .body{flex:1;font-size:14.5px;line-height:1.65;padding-top:4px;white-space:pre-wrap;word-break:break-word}
.n .body pre{background:#0E0E10;border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto;font-size:13px}
.n .body code{background:#141416;padding:1px 6px;border-radius:5px;font-size:13px}
.typing{display:inline-flex;gap:5px;padding:6px 0}
.typing span{width:7px;height:7px;border-radius:50%;background:var(--gold);animation:blink 1.2s infinite}
.typing span:nth-child(2){animation-delay:.2s}.typing span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.25}40%{opacity:1}}
.appr{max-width:760px;margin:0 auto;width:100%;border:1px solid var(--gold);border-radius:14px;padding:16px 18px;background:linear-gradient(180deg,#12100A,#0A0A0C)}
.appr h4{color:var(--gold);font-size:13px;letter-spacing:.06em;margin-bottom:6px}
.appr p{font-size:14px;line-height:1.5;margin-bottom:12px}
.appr .btns{display:flex;gap:10px}
.appr button{flex:1;padding:10px;border-radius:10px;border:none;font-weight:700;font-size:13px;cursor:pointer;transition:.15s}
.appr .ok{background:var(--ok);color:#04170F}.appr .ok:hover{filter:brightness(1.1)}
.appr .no{background:#2A2323;color:var(--no);border:1px solid #3A2A2A}.appr .no:hover{background:#3A2A2A}
input.in{flex:1;background:#0C0C0E;border:1px solid var(--line);color:var(--txt);padding:14px 16px;border-radius:14px;font-size:14px;outline:none}
input.in:focus{border-color:var(--gold)}
.sw{position:relative;width:40px;height:22px;display:inline-block;cursor:pointer}
.sw input{opacity:0;width:0;height:0}
.sw span{position:absolute;inset:0;background:#1E1E22;border-radius:999px;transition:.25s}
.sw span:before{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;background:#8A8678;border-radius:50%;transition:.25s}
.sw input:checked+span{background:var(--gold)}
.sw input:checked+span:before{transform:translateX(18px);background:#111}
button.send{background:var(--gold);color:#111;border:none;border-radius:14px;padding:0 22px;font-weight:700;font-size:15px;cursor:pointer;transition:.15s}
button.send:hover{background:var(--gold2)}
button.send:disabled{opacity:.4;cursor:not-allowed}
.mic{width:48px;background:#0C0C0E;border:1px solid var(--line);color:var(--dim);border-radius:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:.15s}
.mic:hover{color:var(--gold);border-color:var(--gold)}
.mic.live{color:#111;background:var(--gold);border-color:var(--gold);animation:pulseMic 1.4s infinite}
@keyframes pulseMic{0%,100%{box-shadow:0 0 0 0 rgba(201,169,97,.5)}50%{box-shadow:0 0 0 10px rgba(201,169,97,0)}}
#orb{position:fixed;right:26px;bottom:26px;width:120px;height:120px;pointer-events:none;opacity:.92;z-index:50;border-radius:50%}
#orb.idle{opacity:.35}
.bar{max-width:760px;margin:0 auto;width:100%;display:flex;gap:10px;padding-bottom:24px}
.empty{text-align:center;padding:14vh 0 0;color:var(--dim)}
.empty .logo{width:64px;height:64px;border-radius:18px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:800;color:#111;margin:0 auto 18px}
.empty h2{font-size:22px;font-weight:700;margin-bottom:8px}
.empty p{font-size:14px;line-height:1.7}
.empty .sug{margin-top:22px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.empty .sug button{background:#0E0E10;border:1px solid var(--line);color:var(--txt);border-radius:999px;padding:9px 16px;font-size:12.5px;cursor:pointer;transition:.15s}
.empty .sug button:hover{border-color:var(--gold);color:var(--gold)}
/* ===== Right sidebar ===== */
.right{width:300px;background:var(--bg2);border-left:1px solid var(--line);display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto}
.rhead{padding:15px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:9px;font-size:11px;letter-spacing:.16em;color:var(--dim)}
.rhead b{color:var(--txt);font-size:12.5px;letter-spacing:0}
.rsec{padding:15px 18px;border-bottom:1px solid var(--line)}
.rsec h5{font-size:10.5px;letter-spacing:.15em;color:var(--dim);margin-bottom:11px}
.rchip{display:inline-flex;align-items:center;gap:7px;background:#101014;border:1px solid var(--line2);border-radius:999px;padding:6px 12px;font-size:11.5px;color:var(--txt);margin:0 6px 8px 0}
.rchip svg{opacity:.8}
.rstat{display:flex;align-items:center;justify-content:space-between;padding:8px 0;font-size:12px;color:var(--dim);border-bottom:1px dashed #17171B}
.rstat b{color:var(--txt);font-weight:600}
.rcard{border:1px solid var(--line2);border-radius:12px;padding:13px 15px;margin-bottom:10px;background:linear-gradient(180deg,#0E0E12,#0A0A0C)}
.rcard b{font-size:12.5px;display:block;margin-bottom:3px}
.rcard p{font-size:11.5px;color:var(--dim);line-height:1.55}
.rcard .tag{display:inline-block;font-size:10px;color:var(--gold);border:1px solid rgba(201,169,97,.35);border-radius:999px;padding:3px 9px;margin-top:7px}
button.rtab{width:100%;margin-top:10px;padding:11px;border-radius:11px;border:1px solid var(--line2);background:transparent;color:var(--txt);cursor:pointer;font-size:12.5px;transition:.15s;display:flex;align-items:center;justify-content:center;gap:8px}
button.rtab:hover{border-color:var(--gold);color:var(--gold)}
/* ===== Survey modal ===== */
.ovl{position:fixed;inset:0;background:rgba(2,2,4,.78);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;z-index:90}
.ovl.show{display:flex}
.surv{width:520px;max-width:94vw;max-height:88vh;overflow-y:auto;background:var(--bg2);border:1px solid var(--line2);border-radius:20px;padding:26px 28px;box-shadow:0 40px 120px rgba(0,0,0,.7)}
.surv h2{font-size:18px;letter-spacing:.04em;margin-bottom:4px}
.surv .sub{color:var(--dim);font-size:12.5px;margin-bottom:18px}
.sfield{margin-bottom:16px}
.sfield label{display:block;font-size:12px;color:var(--dim);margin-bottom:7px;letter-spacing:.03em}
.sfield textarea,.sfield select,.sfield input{width:100%;background:var(--bg3);border:1px solid var(--line2);color:var(--txt);border-radius:10px;padding:11px 13px;font-size:13px;outline:none;resize:vertical}
.sfield textarea:focus,.sfield select:focus,.sfield input:focus{border-color:var(--gold)}
.stars{display:flex;gap:7px}
.stars button{width:38px;height:38px;border-radius:10px;border:1px solid var(--line2);background:#101014;color:var(--dim);font-size:17px;cursor:pointer;transition:.15s}
.stars button.on{background:var(--gold);color:#111;border-color:var(--gold)}
.surv .row2{display:flex;gap:12px}
.surv .row2 .sfield{flex:1}
.surv .go{width:100%;padding:13px;border-radius:12px;border:none;background:var(--gold);color:#111;font-weight:800;font-size:14px;cursor:pointer;margin-top:6px}
.surv .go:hover{background:var(--gold2)}
.surv .close{position:absolute;top:16px;right:18px;background:none;border:none;color:var(--dim);font-size:18px;cursor:pointer}
.surv .msg{font-size:12.5px;color:var(--ok);margin-top:10px;min-height:16px}
/* auth */
.auth{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:radial-gradient(1200px 700px at 50% -10%,#12100A,var(--bg))}
.card{width:380px;padding:38px 34px;border-radius:22px;border:1px solid var(--line);background:rgba(10,10,12,.9);box-shadow:0 30px 80px rgba(0,0,0,.6)}
.card .logo{width:52px;height:52px;border-radius:14px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;color:#111;margin-bottom:18px}
.card h1{font-size:20px;margin-bottom:4px}
.card .sub{color:var(--dim);font-size:13px;margin-bottom:24px}
.card label{display:block;font-size:12px;color:var(--dim);margin:14px 0 6px;letter-spacing:.05em}
.card input{width:100%;background:#0C0C0E;border:1px solid var(--line);color:var(--txt);padding:12px 14px;border-radius:12px;font-size:14px;outline:none}
.card input:focus{border-color:var(--gold)}
.card button{width:100%;margin-top:22px;padding:13px;border-radius:12px;border:none;background:var(--gold);color:#111;font-weight:700;font-size:14px;cursor:pointer}
.card button:hover{background:var(--gold2)}
.card .err{color:var(--no);font-size:12.5px;margin-top:10px;min-height:16px}
.card .alt{margin-top:16px;text-align:center;font-size:13px;color:var(--dim)}
.card .alt a{color:var(--gold);text-decoration:none}
@media(max-width:820px){.side{display:none}.right{display:none}}
</style>
</head>
<body>
<div class="side">
  <div class="brand"><img src="/nova-logo.png"><div><h1>AURA AI</h1><small>YOUR LOCAL ASSISTANT</small></div></div>
  <button class="newbtn" onclick="newChat()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>New chat</button>
  <div class="navgrp">
    <button class="navitem on" id="navchat" onclick="goChat()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Chat</button>
    <button class="navitem" id="navclients" style="display:none" onclick="showClients()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>Clients · activity</button>
    <button class="navitem" onclick="toggleVideoPanel()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m22 8-6 4 6 4V8Z"/><rect x="2" y="6" width="14" height="12" rx="2"/></svg>Video Studio</button>
    <button class="navitem" id="adminbtn" style="display:none" onclick="location.href='/admin'"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>Admin panel</button>
  </div>
  <div class="hist" id="histbox"><h4>RECENT CHATS</h4><div id="histlist"></div></div>
  <div class="foot">
    <div class="user"><div class="av" id="av"></div><div><b id="who"></b><small>Signed in</small></div></div>
    <div>Level <span id="lvl"></span> · every risky action asks first.<br>All actions are audited.</div>
    <div class="godrow"><span style="letter-spacing:.08em">GOD MODE</span><label class="sw"><input type="checkbox" id="god" onchange="setGod(this.checked)"><span></span></label></div>
    <div class="godrow" style="margin-top:6px"><a class="logout" href="/logout" style="font-size:11px">Sign out</a></div>
  </div>
</div>
<div class="mid">
  <div class="top"><b id="curtitle">Chat</b><div class="acc"><button class="rtab" onclick="openSurvey()" style="margin-top:0;padding:8px 14px;font-size:11.5px">Give feedback</button></div></div>
  <div class="chat" id="chat"></div>
  <div style="border-top:1px solid var(--line);padding:14px">
    <div class="bar"><button class="mic" id="mic" onclick="toggleMic()" title="Voice input"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="22"/></svg></button><input class="in" id="inp" placeholder="Ask Aura anything..." autocomplete="off"><button class="send" id="btn">Send</button></div>
  </div>
  <canvas id="orb"></canvas>
</div>
<div class="right">
  <div class="rhead"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="var(--gold)" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg><b>Aura</b>&nbsp;· session</div>
  <div class="rsec"><h5>SESSION</h5>
    <div class="rstat"><span>Permission level</span><b id="rlvl">1</b></div>
    <div class="rstat"><span>God mode</span><b id="rgod">OFF</b></div>
    <div class="rstat"><span>Workspace</span><b style="font-size:10.5px">nova_workspace</b></div>
  </div>
  <div class="rsec"><h5>CAPABILITIES</h5>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>Files</span>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12c.6.8 1 2 1 3h6c0-1 .4-2.2 1-3a7 7 0 0 0-4-12z"/></svg>Notes</span>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>Browser</span>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>Apps</span>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>Schedule</span>
    <span class="rchip"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2"><path d="m22 8-6 4 6 4V8Z"/><rect x="2" y="6" width="14" height="12" rx="2"/></svg>Video studio</span>
  </div>
  <div class="rsec"><h5>RECENT FILES</h5><div id="rfiles"><div class="rcard"><b>Empty workspace</b><p>Files you ask Aura to create will appear here.</p></div></div></div>
  <div class="rsec"><h5>HELP US IMPROVE</h5>
    <div class="rcard"><b>Test Aura, share your thoughts</b><p>5 quick questions. Your answers go straight to the owner dashboard.</p>
      <span class="tag">Takes ~1 minute</span></div>
    <button class="rtab" onclick="openSurvey()"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Open survey</button>
  </div>
</div>
<div class="ovl" id="ovl" onclick="if(event.target===this)closeSurvey()">
  <div class="surv" style="position:relative">
    <button class="close" onclick="closeSurvey()">✕</button>
    <h2>Help us improve Aura</h2>
    <div class="sub">5 short questions — your answers go straight to the owner.</div>
    <div class="sfield"><label>1 · How would you rate Aura overall?</label><div class="stars" id="stars"><button onclick="setStar(1)">★</button><button onclick="setStar(2)">★</button><button onclick="setStar(3)">★</button><button onclick="setStar(4)">★</button><button onclick="setStar(5)">★</button></div></div>
    <div class="row2">
      <div class="sfield"><label>2 · Was it fast enough?</label><select id="sf_speed"><option value="">Select…</option><option>Fast</option><option>Okay</option><option>Slow</option></select></div>
      <div class="sfield"><label>3 · Would you use it again?</label><select id="sf_recommend"><option value="">Select…</option><option>Yes, definitely</option><option>Maybe</option><option>No</option></select></div>
    </div>
    <div class="sfield"><label>4 · What was most useful?</label><input id="sf_useful" placeholder="e.g. notes, browsing, video…"></div>
    <div class="sfield"><label>5 · What should we improve?</label><textarea id="sf_missing" rows="2" placeholder="Anything missing or confusing?"></textarea></div>
    <button class="go" onclick="submitSurvey()">Submit feedback</button>
    <div class="msg" id="sfmsg"></div>
  </div>
</div>
<div id="vpanel" style="display:none;position:fixed;right:24px;top:24px;bottom:24px;width:380px;max-width:92vw;background:var(--bg2);border:1px solid var(--gold);border-radius:16px;z-index:50;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.6)">
  <div style="padding:16px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between">
    <b style="letter-spacing:.12em">VIDEO STUDIO</b>
    <a href="javascript:void(0)" onclick="toggleVideoPanel()" style="color:var(--dim);font-size:16px;text-decoration:none">✕</a>
  </div>
  <div style="padding:16px 18px;overflow-y:auto;flex:1">
    <div style="display:flex;gap:8px;margin-bottom:14px">
      <button class="vtab" id="vtabgen" onclick="vTab('gen')" style="flex:1;padding:9px;border-radius:10px;border:1px solid var(--gold);background:var(--gold);color:#111;font-weight:700;cursor:pointer">Generate</button>
      <button class="vtab" id="vtabedit" onclick="vTab('edit')" style="flex:1;padding:9px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--txt);cursor:pointer">Edit</button>
    </div>
    <label style="display:block;font-size:11px;color:var(--dim);margin:8px 0 4px">PROMPT</label>
    <textarea id="vprompt" rows="3" style="width:100%;background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:13px;resize:vertical" placeholder="Describe the video you want..."></textarea>
    <div id="vurlrow" style="display:none;margin-top:10px">
      <label style="display:block;font-size:11px;color:var(--dim);margin:8px 0 4px">SOURCE VIDEO URL</label>
      <input id="vurl" type="url" style="width:100%;background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:13px" placeholder="https://...video.mp4">
    </div>
    <div style="display:flex;gap:8px;margin-top:12px">
      <select id="vratio" style="background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:9px;font-size:12px">
        <option value="16:9">16:9</option><option value="9:16">9:16</option><option value="1:1">1:1</option><option value="4:3">4:3</option>
      </select>
      <select id="vdur" style="background:var(--bg);color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:9px;font-size:12px">
        <option value="6">6s</option><option value="8">8s</option><option value="10">10s</option><option value="12">12s</option>
      </select>
    </div>
    <button id="vgo" onclick="vRun()" style="width:100%;margin-top:14px;padding:12px;border-radius:12px;border:none;background:var(--gold);color:#111;font-weight:800;cursor:pointer">Generate video</button>
    <div id="vmsg" style="margin-top:12px;font-size:12px;color:var(--dim);line-height:1.6"></div>
    <div id="vout" style="margin-top:12px"></div>
  </div>
</div>
<script>
const chat=document.getElementById('chat'),inp=document.getElementById('inp'),btn=document.getElementById('btn');
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function addMsg(role,text){
  const w=document.createElement('div');w.className='wrap';
  const m=document.createElement('div');m.className='m '+role;
  m.innerHTML=(role==='u'?'<div class="ic">YOU</div>':'<div class="ic"><img src="/nova-logo.png" style="width:30px;height:30px;border-radius:8px;object-fit:cover"></div>')+'<div class="body">'+esc(text)+'</div>';
  w.appendChild(m);chat.appendChild(w);chat.scrollTop=chat.scrollHeight;return w;
}
function addTyping(){const w=document.createElement('div');w.className='wrap';w.innerHTML='<div class="m n"><div class="ic"><img src="/nova-logo.png" style="width:30px;height:30px;border-radius:8px;object-fit:cover"></div><div class="body"><span class="typing"><span></span><span></span><span></span></span></div></div>';chat.appendChild(w);chat.scrollTop=chat.scrollHeight;return w;}
async function send(){
  const v=inp.value.trim();if(!v||btn.disabled)return;
  inp.value='';btn.disabled=true;addMsg('u',v);addToHist('u',v);
  const t=addTyping();orbEnergy=1;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:v})});
    const d=await r.json();
    t.remove();orbEnergy=0.6;
    if(d.reply){addMsg('n',d.reply);addToHist('n',d.reply);}
    if(d.error){addMsg('n','Error: '+d.error);addToHist('n','Error: '+d.error);}
    pollApprovals();
  }catch(e){t.remove();orbEnergy=0.3;addMsg('n','Network error: '+e);addToHist('n','Network error: '+e);}
  btn.disabled=false;inp.focus();
}
async function pollApprovals(){
  const r=await fetch('/api/approvals');const d=await r.json();
  document.querySelectorAll('.appr').forEach(e=>e.remove());
  d.approvals.forEach(a=>{
    const w=document.createElement('div');w.className='wrap';
    w.innerHTML=`<div class="appr"><h4>ACTION REQUIRES APPROVAL</h4><p>${esc(a.action)}${a.details?'<br><small style="color:var(--dim)">'+esc(a.details)+'</small>':''}</p><div class="btns"><button class="ok">Approve</button><button class="no">Deny</button></div></div>`;
    w.querySelector('.ok').onclick=()=>decide(a.token,true);
    w.querySelector('.no').onclick=()=>decide(a.token,false);
    chat.appendChild(w);chat.scrollTop=chat.scrollHeight;
  });
}
async function decide(token,ok){
  await fetch('/api/approvals/decide',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,ok})});
  setTimeout(pollApprovals,600);
}
let hist=[],curId=null;
function histKey(){return 'aura_chats_'+(localStorage.getItem('aura_user')||'guest');}
function loadHistAll(){try{return JSON.parse(localStorage.getItem(histKey()))||[]}catch(e){return []}}
function saveHistAll(h){try{localStorage.setItem(histKey(),JSON.stringify(h))}catch(e){}}
function newChat(){
  if(hist.length){
    const all=loadHistAll();
    all.unshift({t:hist[0].text.slice(0,40),m:hist,ts:Date.now()});
    saveHistAll(all.slice(0,30));
  }
  hist=[];curId=null;chat.innerHTML='';chat.appendChild(emptyHTML());renderHist();inp.focus();
}
function goChat(){
  document.getElementById('navchat').classList.add('on');
  document.getElementById('navclients').classList.remove('on');
  document.getElementById('curtitle').textContent='Chat';
  chat.innerHTML='';
  if(hist.length){hist.forEach(m=>addMsg(m.role,m.text));}
  else{chat.appendChild(emptyHTML());}
}
function renderHist(){
  const box=document.getElementById('histlist');
  const all=loadHistAll();
  if(!all.length){box.innerHTML='<div style="font-size:11.5px;color:var(--dim);padding:6px 8px">No chats yet — start one above.</div>';return;}
  box.innerHTML=all.map((c,i)=>`<button class="hit" onclick="openHist(${i})">${esc(c.t)}</button>`).join('');
}
function openHist(i){
  const all=loadHistAll();
  if(!all[i])return;
  hist=all[i].m;curId=null;goChat();chat.scrollTop=chat.scrollHeight;
}
function addToHist(role,text){
  hist.push({role,text});
  if(hist.length>200)hist=hist.slice(-200);
}
async function showClients(){
  document.getElementById('navchat').classList.remove('on');
  document.getElementById('navclients').classList.add('on');
  document.getElementById('curtitle').textContent='Clients · activity';
  chat.innerHTML='';
  const w=document.createElement('div');w.className='wrap';
  w.innerHTML='<div class="empty"><img src="/nova-logo.png" style="width:64px;height:64px;border-radius:18px;object-fit:cover;margin:0 auto 18px;display:block"><h2>Client activity</h2><p>Loading who did what…</p></div>';
  chat.appendChild(w);chat.scrollTop=chat.scrollHeight;
  try{
    const r=await fetch('/api/activity');const d=await r.json();
    let html='<div class="wrap"><div class="empty" style="padding-top:6vh"><img src="/nova-logo.png" style="width:64px;height:64px;border-radius:18px;object-fit:cover;margin:0 auto 18px;display:block"><h2>Clients · who did what</h2></div>';
    if(!d.clients.length)html+='<p style="text-align:center;color:var(--dim);font-size:13px">No clients yet.</p>';
    d.clients.forEach(c=>{
      html+=`<div style="border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:12px">
        <b style="font-size:14px">${esc(c.name)}</b> <span style="color:var(--dim);font-size:12px">${esc(c.email)} · ${c.provider==='google'?'Google':'email'}</span>
        <div style="font-size:12px;color:var(--dim);margin-top:6px;line-height:1.8">
        Signed up ${new Date(c.signed_up*1000).toLocaleString()} · last seen ${c.last_seen?new Date(c.last_seen*1000).toLocaleString():'—'}<br>
        ${c.chats} chats · ${c.god_toggles} god toggles · ${c.events} total events</div></div>`;
    });
    html+='<h3 style="font-size:13px;letter-spacing:.06em;color:var(--gold);margin:20px 0 10px">Recent activity</h3>';
    d.events.forEach(e=>{
      html+=`<div style="font-size:12.5px;color:var(--dim);border-bottom:1px solid var(--line-soft);padding:7px 0;display:flex;gap:10px">
        <span style="flex:none;width:150px;color:var(--gold)">${new Date(e.ts*1000).toLocaleString()}</span>
        <span style="flex:none;width:80px">${esc(e.action)}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.email||'')} ${esc(e.detail||'')}</span></div>`;
    });
    html+='<div style="height:30px"></div></div>';
    chat.innerHTML=html;chat.scrollTop=0;
  }catch(err){chat.innerHTML='<div class="wrap"><p style="color:var(--no);text-align:center">Failed to load activity.</p></div>';}
}
function emptyHTML(){
  const d=document.createElement('div');d.className='wrap';
  d.innerHTML=`<div class="empty"><img src="/nova-logo.png" style="width:64px;height:64px;border-radius:18px;object-fit:cover;margin:0 auto 18px;display:block"><h2>How can I help you?</h2>
  <p>I can manage files, remember notes, browse the web, open apps, run scheduled jobs and create videos.<br>Risky actions always ask for your approval first.</p>
  <div class="sug"><button onclick="q('List my files in the workspace')">List my files</button><button onclick="q('Save a note: remember this')">Save a note</button><button onclick="q('Open Wikipedia and summarize the front page')">Browse the web</button><button onclick="q('What can you do?')">What can you do?</button></div></div>`;
  return d;
}
function q(t){inp.value=t;send();}
async function setGod(on){
  await fetch('/api/god',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on})});
  document.getElementById('rgod').textContent=on?'ON':'OFF';
  pollApprovals();
}
async function me(){const r=await fetch('/api/me');const d=await r.json();
  document.getElementById('who').textContent=d.name;document.getElementById('av').textContent=d.name[0].toUpperCase();
  document.getElementById('lvl').textContent=d.level;
  document.getElementById('rlvl').textContent=d.level;
  document.getElementById('rgod').textContent=d.god?'ON':'OFF';
  document.getElementById('god').checked=!!d.god;
  document.title='Aura AI — '+d.name;
  localStorage.setItem('aura_user',d.name);
  if(d.owner){document.getElementById('adminbtn').style.display='block';document.getElementById('navclients').style.display='block';}
  renderHist();
}
/* ---- Survey ---- */
let star=0;
function openSurvey(){document.getElementById('ovl').classList.add('show');}
function closeSurvey(){document.getElementById('ovl').classList.remove('show');}
function setStar(n){
  star=n;
  document.querySelectorAll('#stars button').forEach((b,i)=>b.classList.toggle('on',i<n));
}
async function submitSurvey(){
  const msg=document.getElementById('sfmsg');
  const body={
    rating:star,
    speed:document.getElementById('sf_speed').value,
    useful:document.getElementById('sf_useful').value.trim(),
    missing:document.getElementById('sf_missing').value.trim(),
    recommend:document.getElementById('sf_recommend').value,
  };
  if(!star){msg.style.color='var(--no)';msg.textContent='Please pick a star rating.';return;}
  try{
    const r=await fetch('/api/survey',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    msg.style.color='var(--ok)';
    msg.textContent=d.ok?'Thanks! Your feedback was saved.':'Error: '+(d.error||'Failed.');
    if(d.ok){setTimeout(closeSurvey,1300);}
  }catch(e){msg.style.color='var(--no)';msg.textContent='Network error: '+e;}
}
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
btn.addEventListener('click',send);
me();chat.appendChild(emptyHTML());
setInterval(pollApprovals,2500);inp.focus();

/* ---- Video Studio ---- */
let vMode='gen';
function toggleVideoPanel(){
  const p=document.getElementById('vpanel');
  const open=(p.style.display==='flex');
  p.style.display=open?'none':'flex';
  if(!open)vStatus();
}
function vTab(mode){
  vMode=mode;
  document.getElementById('vtabgen').style.background=mode==='gen'?'var(--gold)':'transparent';
  document.getElementById('vtabgen').style.color=mode==='gen'?'#111':'var(--txt)';
  document.getElementById('vtabedit').style.background=mode==='edit'?'var(--gold)':'transparent';
  document.getElementById('vtabedit').style.color=mode==='edit'?'#111':'var(--txt)';
  document.getElementById('vurlrow').style.display=mode==='edit'?'block':'none';
  document.getElementById('vgo').textContent=mode==='gen'?'Generate video':'Edit video';
}
async function vStatus(){
  try{
    const r=await fetch('/api/video/status');const d=await r.json();
    const m=document.getElementById('vmsg');
    if(d.ok&&d.enabled){m.textContent='Ready. Model: '+d.model;}
    else{m.textContent='Video Studio is not configured yet (no VIDEO_API_KEY). The panel will unlock once the owner adds a key.';}
  }catch(e){}
}
async function vRun(){
  const m=document.getElementById('vmsg'),out=document.getElementById('vout');
  const prompt=document.getElementById('vprompt').value.trim();
  const ratio=document.getElementById('vratio').value;
  const dur=document.getElementById('vdur').value;
  const url=document.getElementById('vurl').value.trim();
  m.textContent='Working — video generation can take a few minutes...';out.innerHTML='';
  try{
    let d;
    if(vMode==='gen'){
      const r=await fetch('/api/video/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,duration:dur,ratio})});
      d=await r.json();
    }else{
      const r=await fetch('/api/video/edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,video_url:url})});
      d=await r.json();
    }
    if(d.ok&&d.video_url){
      m.textContent='Done. Video is ready:';
      out.innerHTML='<video src="'+d.video_url+'" controls style="width:100%;border-radius:12px;background:#000"></video>';
    }else{
      m.textContent='Error: '+(d.error||'unknown');
    }
  }catch(e){m.textContent='Network error: '+e;}
}

/* ---- 3D voice orb (Three.js) ---- */
const orbCanvas=document.getElementById('orb'),orbCtx=orbCanvas.getContext('2d');
let orbEnergy=0,orbPhase=0;
function drawOrb(){
  const t=performance.now()/1000;orbPhase+=0.016;
  const size=120,cx=60,cy=60;
  orbCtx.clearRect(0,0,size,size);
  const pulse=orbEnergy>0.02?1+Math.sin(t*3)*0.06*orbEnergy:1;
  // outer halo
  const g1=orbCtx.createRadialGradient(cx,cy,4,cx,cy,58);
  g1.addColorStop(0,'rgba(229,205,142,'+(0.25+orbEnergy*0.5)+')');
  g1.addColorStop(1,'rgba(201,169,97,0)');
  orbCtx.fillStyle=g1;orbCtx.beginPath();orbCtx.arc(cx,cy,58,0,7);orbCtx.fill();
  // core
  const g2=orbCtx.createRadialGradient(cx-4,cy-5,1,cx,cy,26*pulse);
  g2.addColorStop(0,'#F4E3B2');g2.addColorStop(.45,'#C9A961');g2.addColorStop(1,'rgba(138,115,58,0)');
  orbCtx.fillStyle=g2;orbCtx.beginPath();orbCtx.arc(cx,cy,26*pulse,0,7);orbCtx.fill();
  // sparkle ring
  orbCtx.strokeStyle='rgba(229,205,142,'+(0.3+orbEnergy*0.4)+')';
  orbCtx.lineWidth=1.5;
  orbCtx.beginPath();orbCtx.arc(cx,cy,36*pulse,orbPhase,orbPhase+4.2);orbCtx.stroke();
  orbEnergy*=0.985;
  requestAnimationFrame(drawOrb);
}
drawOrb();

/* ---- voice input (Web Speech API) ---- */
let rec=null,recOn=false;
function toggleMic(){
  const mic=document.getElementById('mic');
  if(recOn){if(rec)rec.stop();return;}
  if(!('webkitSpeechRecognition' in window)&&!('SpeechRecognition' in window)){
    inp.value='Sorry, voice input is not supported in this browser.';return;
  }
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  rec=new SR();rec.lang='en-US';rec.interimResults=false;rec.maxAlternatives=1;
  rec.onstart=()=>{recOn=true;mic.classList.add('live');orbEnergy=1;};
  rec.onresult=e=>{inp.value=e.results[0][0].transcript;orbEnergy=0.8;};
  rec.onend=()=>{recOn=false;mic.classList.remove('live');if(inp.value.trim())send();};
  rec.onerror=()=>{recOn=false;mic.classList.remove('live');};
  rec.start();
}
</script>
</body>
</html>
"""

AUTH_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aura AI</title>
<link rel="icon" href="/nova-logo.png">
<style>
:root{--bg:#050505;--gold:#C9A961;--gold2:#E5CD8E;--txt:#EDEAE2;--dim:#8A8678;--line:#1E1E22;--no:#E06666}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 700px at 50% -10%,#12100A,var(--bg));color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{width:390px;padding:40px 36px;border-radius:22px;border:1px solid var(--line);background:rgba(10,10,12,.9);box-shadow:0 30px 80px rgba(0,0,0,.6)}
.logo{width:54px;height:54px;border-radius:15px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;color:#111;margin-bottom:20px}
h1{font-size:21px;margin-bottom:4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:26px;line-height:1.5}
label{display:block;font-size:12px;color:var(--dim);margin:14px 0 6px;letter-spacing:.05em}
input{width:100%;background:#0C0C0E;border:1px solid var(--line);color:var(--txt);padding:13px 14px;border-radius:12px;font-size:14px;outline:none}
input:focus{border-color:var(--gold)}
button{width:100%;margin-top:22px;padding:13px;border-radius:12px;border:none;background:var(--gold);color:#111;font-weight:700;font-size:14px;cursor:pointer}
button:hover{background:var(--gold2)}
.err{color:var(--no);font-size:12.5px;margin-top:10px;min-height:16px}
.alt{margin-top:18px;text-align:center;font-size:13px;color:var(--dim)}
.alt a{color:var(--gold);text-decoration:none}
.or{display:flex;align-items:center;gap:12px;color:var(--dim);font-size:12px;margin:16px 0 2px;letter-spacing:.06em}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
#gwrap{margin-top:6px}
</style>
</head>
<body>
<div class="card">
<div class="logo"><img src="/nova-logo.png" style="width:54px;height:54px;border-radius:15px;object-fit:cover"></div>
<h1 id="t1">Welcome back</h1>
<div class="sub" id="t2">Sign in to your Aura AI workspace.</div>
<div id="gwrap"></div>
<div class="or"><span>or</span></div>
<form id="f" onsubmit="go(event)">
<div id="namewrap" style="display:none"><label>Full name</label><input id="name" placeholder="Your name" autocomplete="name"></div>
<label id="l_email">Email</label><input id="email" placeholder="you@email.com" autocomplete="email" required>
<label id="l_pw">Password</label><input id="pw" type="password" placeholder="••••••••" autocomplete="current-password" required>
<div class="err" id="err"></div>
<button id="b">Sign in</button>
</form>
<div class="alt" id="alt">New here? <a href="#" onclick="toggle(event)">Create an account</a></div>
<div class="alt"><a href="#" onclick="forgot(event)">Forgot password?</a></div>
</div>
<script>
let mode='login';
const t1=document.getElementById('t1'),t2=document.getElementById('t2'),b=document.getElementById('b'),
namewrap=document.getElementById('namewrap'),alt=document.getElementById('alt'),
l_email=document.getElementById('l_email'),l_pw=document.getElementById('l_pw'),
email=document.getElementById('email'),pw=document.getElementById('pw');
function toggle(e){e.preventDefault();mode=mode==='login'?'signup':'login';
namewrap.style.display=mode==='signup'?'block':'none';
t1.textContent=mode==='signup'?'Create your account':'Welcome back';
t2.textContent=mode==='signup'?'Start chatting with your personal Aura.':'Sign in to your Aura AI workspace.';
b.textContent=mode==='signup'?'Create account':'Sign in';
l_pw.style.display='block';pw.style.display='block';
alt.innerHTML=mode==='signup'?'Already have one? <a href="#" onclick="toggle(event)">Sign in</a>':'New here? <a href="#" onclick="toggle(event)">Create an account</a>';}
async function forgot(e){e.preventDefault();mode='forgot';
t1.textContent='Reset password';t2.textContent='Enter your email and we will send you a reset link.';
namewrap.style.display='none';l_pw.style.display='none';pw.style.display='none';
b.textContent='Send reset link';
alt.innerHTML='Remembered? <a href="#" onclick="location.reload()">Sign in</a>';
document.getElementById('err').textContent='';}
async function go(e){e.preventDefault();const err=document.getElementById('err');err.textContent='';
if(mode==='forgot'){
  const r=await fetch('/api/auth/forgot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.value})});
  const d=await r.json();
  if(d.link){err.style.color='#E5CD8E';err.textContent=d.note+' '+d.link;}
  else if(d.ok){err.style.color='#E5CD8E';err.textContent=d.note;}
  else{err.textContent=d.error||'Something went wrong';}
  return;}
const body={mode,email:email.value,password:pw.value};
if(mode==='signup')body.name=document.getElementById('name').value;
const r=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const d=await r.json();
if(d.ok){location.href='/chat';}else{err.textContent=d.error||'Something went wrong';}}
/* Google Sign-In */
fetch('/api/config').then(r=>r.json()).then(cfg=>{
  if(!cfg.google_client_id)return;
  const s=document.createElement('script');s.src='https://accounts.google.com/gsi/client';s.async=true;s.onload=()=>{
    google.accounts.id.initialize({client_id:cfg.google_client_id,callback:resp=>{
      fetch('/api/auth/google',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({credential:resp.credential})})
        .then(r=>r.json()).then(d=>{if(d.ok){location.href='/chat';}else{document.getElementById('err').textContent=d.error||'Google sign-in failed';}});
    }});
    google.accounts.id.renderButton(document.getElementById('gwrap'),{theme:'filled_black',size:'large',width:316,shape:'pill',text:'continue_with'});
  };
  document.head.appendChild(s);
});
</script>
</body>
</html>
"""

RESET_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aura AI — Reset password</title>
<link rel="icon" href="/nova-logo.png">
<style>
:root{--bg:#050505;--gold:#C9A961;--gold2:#E5CD8E;--txt:#EDEAE2;--dim:#8A8678;--line:#1E1E22;--no:#E06666}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 700px at 50% -10%,#12100A,var(--bg));color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{width:390px;padding:40px 36px;border-radius:22px;border:1px solid var(--line);background:rgba(10,10,12,.9);box-shadow:0 30px 80px rgba(0,0,0,.6)}
.logo{width:54px;height:54px;border-radius:15px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;color:#111;margin-bottom:20px}
h1{font-size:21px;margin-bottom:4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:26px;line-height:1.5}
label{display:block;font-size:12px;color:var(--dim);margin:14px 0 6px;letter-spacing:.05em}
input{width:100%;background:#0C0C0E;border:1px solid var(--line);color:var(--txt);padding:13px 14px;border-radius:12px;font-size:14px;outline:none}
input:focus{border-color:var(--gold)}
button{width:100%;margin-top:22px;padding:13px;border-radius:12px;border:none;background:var(--gold);color:#111;font-weight:700;font-size:14px;cursor:pointer}
button:hover{background:var(--gold2)}
.msg{color:var(--gold2);font-size:13px;margin-top:12px;min-height:16px;word-break:break-all}
.err{color:var(--no);font-size:12.5px;margin-top:10px;min-height:16px}
</style>
</head>
<body>
<div class="card">
<div class="logo"><img src="/nova-logo.png" style="width:54px;height:54px;border-radius:15px;object-fit:cover"></div>
<h1>Set a new password</h1>
<div class="sub">Choose a new password for your Aura AI account.</div>
<label>New password</label><input id="pw" type="password" placeholder="At least 4 characters">
<div class="err" id="err"></div>
<div class="msg" id="msg"></div>
<button onclick="go()">Update password</button>
</div>
<script>
const token=new URLSearchParams(location.search).get('token');
async function go(){
  const err=document.getElementById('err'),msg=document.getElementById('msg');
  err.textContent='';msg.textContent='';
  const r=await fetch('/api/auth/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,password:document.getElementById('pw').value})});
  const d=await r.json();
  if(d.ok){msg.textContent=d.note;setTimeout(()=>location.href='/',1800);}
  else{err.textContent=d.error||'Something went wrong';}
}
</script>
</body>
</html>
"""

ADMIN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aura AI — Admin</title>
<link rel="icon" href="/nova-logo.png">
<style>
:root{--bg:#050505;--bg2:#0A0A0C;--gold:#C9A961;--gold2:#E5CD8E;--txt:#EDEAE2;--dim:#8A8678;--line:#1E1E22;--ok:#5EC8A5;--no:#E06666}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;padding:34px 22px 80px}
.wrap{max-width:980px;margin:0 auto}
.top{display:flex;align-items:center;gap:12px;margin-bottom:26px;flex-wrap:wrap}
.logo{width:40px;height:40px;border-radius:10px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-weight:800;color:#111}
h1{font-size:20px;letter-spacing:.06em}
.top .who{color:var(--dim);font-size:13px;margin-left:auto}
a{color:var(--gold);text-decoration:none;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-bottom:26px}
.stat{border:1px solid var(--line);border-radius:16px;padding:18px 20px;background:var(--bg2)}
.stat b{display:block;font-size:26px;color:var(--gold);margin-bottom:4px}
.stat span{font-size:12.5px;color:var(--dim)}
.sec{border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:20px;background:var(--bg2)}
.sec h2{font-size:14px;letter-spacing:.08em;color:var(--gold);margin-bottom:14px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
button{padding:10px 16px;border-radius:10px;border:none;background:#141416;color:var(--txt);font-size:13px;cursor:pointer;transition:.15s}
button:hover{border:1px solid var(--gold);color:var(--gold)}
button.gold{background:var(--gold);color:#111;font-weight:700}
button.gold:hover{background:var(--gold2);color:#111}
button.danger{background:#2A2323;color:var(--no);border:1px solid #3A2A2A}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--dim);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);font-size:12px;letter-spacing:.04em}
td{padding:9px 10px;border-bottom:1px solid #151518;vertical-align:top}
td small{color:var(--dim)}
.out{background:#0E0E10;border:1px solid var(--line);border-radius:10px;padding:14px;font-family:Consolas,monospace;font-size:12.5px;white-space:pre-wrap;max-height:260px;overflow:auto;display:none}
.row{display:flex;gap:8px;align-items:center}
@media(max-width:640px){table{font-size:12px}th,td{padding:6px 6px}}
</style>
</head>
<body>
<div class="wrap">
<div class="top">
  <div class="logo"><img src="/nova-logo.png" style="width:40px;height:40px;border-radius:10px;object-fit:cover"></div>
  <h1>AURA ADMIN</h1>
  <span class="who" id="who"></span>
  <a href="/chat">Back to chat</a>
</div>
<div class="grid" id="stats"></div>
<div class="sec">
  <h2>ACTIONS</h2>
  <div class="actions">
    <button class="gold" onclick="backup()">Download full backup (JSON)</button>
    <button class="gold" onclick="upgrade()">Self-upgrade (git pull)</button>
    <button id="godbtn" onclick="toggleGod()">Global God Mode: OFF</button>
    <button onclick="refresh()">Refresh data</button>
  </div>
  <div class="out" id="out"></div>
</div>
<div class="sec">
  <h2>USERS · FULL ACCESS</h2>
  <table>
    <thead><tr><th>Name</th><th>Email</th><th>Provider</th><th>Signed up</th><th>Last seen</th><th>Chats</th><th>Events</th><th>Actions</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<div class="sec">
  <h2>USER FEEDBACK SURVEY</h2>
  <div class="actions">
    <button class="gold" onclick="loadSurveys()">Refresh surveys</button>
    <button onclick="exportSurveys()">Export CSV</button>
    <span id="sstats" style="font-size:12.5px;color:var(--dim);align-self:center"></span>
  </div>
  <table>
    <thead><tr><th>When</th><th>Name / Email</th><th>Rating</th><th>Speed</th><th>Most useful</th><th>Improve</th><th>Recommend</th></tr></thead>
    <tbody id="srows"></tbody>
  </table>
</div>
<div class="sec">
  <h2>RECENT ACTIVITY</h2>
  <table><tbody id="events"></tbody></table>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
function showOut(t){const o=$('out');o.style.display='block';o.textContent=t;}
async function refresh(){
  const [s,u,e]=await Promise.all([
    fetch('/api/activity').then(r=>r.json()),
    fetch('/api/admin/users').then(r=>r.json()),
    fetch('/api/admin/activity').then(r=>r.json()),
  ]);
  const clients=s.clients||[];
  $('stats').innerHTML=[
    ['Users',clients.length],
    ['Total chats',clients.reduce((a,c)=>a+(c.chats||0),0)],
    ['Total events',clients.reduce((a,c)=>a+(c.events||0),0)],
    ['Recent events',(e.events||[]).length],
  ].map(x=>`<div class="stat"><b>${x[1]}</b><span>${x[0]}</span></div>`).join('');
  $('rows').innerHTML=(u.users||[]).map(x=>`<tr>
    <td><b>${esc(x.name)}</b></td>
    <td>${esc(x.email)}</td>
    <td><small>${esc(x.provider)}</small></td>
    <td><small>${x.signed_up?new Date(x.signed_up*1000).toLocaleString():'—'}</small></td>
    <td><small>${x.last_seen?new Date(x.last_seen*1000).toLocaleString():'—'}</small></td>
    <td>${x.chats||0}</td>
    <td>${x.events||0}</td>
    <td><div class="row">
      <button onclick="resetPw(${x.id})">Reset password</button>
      <button class="danger" onclick="del(${x.id},'${esc(x.email)}')">Delete</button>
    </div></td></tr>`).join('');
  $('events').innerHTML=(e.events||[]).map(x=>`<tr>
    <td><small>${new Date(x.ts*1000).toLocaleString()}</small></td>
    <td><b>${esc(x.action)}</b></td>
    <td><small>${esc(x.email||'')} ${esc(x.detail||'')}</small></td></tr>`).join('');
}
async function backup(){
  showOut('Preparing backup…');
  const r=await fetch('/api/admin/backup');
  const blob=await r.blob();
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='aura-backup.json';
  a.click();
  showOut('Backup downloaded. Keep it safe — upload it to your own cloud storage.');
}
async function upgrade(){
  showOut('Running self-upgrade…');
  const r=await fetch('/api/admin/upgrade',{method:'POST'});
  const d=await r.json();
  showOut(d.ok?'Upgrade OK — latest code pulled:\n'+(d.out||''):'Upgrade failed:\n'+(d.error||d.out||''));
}
async function toggleGod(){
  const r=await fetch('/api/admin/god',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:godNow})});
  const d=await r.json();
  godNow=!godNow;
  $('godbtn').textContent='Global God Mode: '+(godNow?'ON':'OFF');
  showOut(d.ok?'Global God Mode is now '+(godNow?'ON':'OFF')+'. All approvals auto-accept.':'Failed.');
}
let godNow=false;
async function resetPw(uid){
  const r=await fetch('/api/admin/reset-user-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid})});
  const d=await r.json();
  showOut(d.ok?('Reset link for '+d.email+':\n'+d.link):(d.error||'Failed.'));
}
async function del(uid,email){
  if(!confirm('Delete user '+email+' and all their activity? This cannot be undone.'))return;
  const r=await fetch('/api/admin/delete-user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid})});
  const d=await r.json();
  showOut(d.ok?'User deleted.':(d.error||'Failed.'));
  refresh();
}
async function loadSurveys(){
  const r=await fetch('/api/admin/surveys');
  const d=await r.json();
  const st=d.stats||{};
  $('sstats').textContent=st.count+' responses · avg '+(st.avg||0)+'/5';
  $('srows').innerHTML=(d.surveys||[]).map(x=>`<tr>
    <td><small>${x.ts?new Date(x.ts*1000).toLocaleString():'—'}</small></td>
    <td><b>${esc(x.name||'')}</b><br><small>${esc(x.email||'')}</small></td>
    <td><b style="color:var(--gold)">${'★'.repeat(x.rating||0)}${'☆'.repeat(Math.max(0,5-(x.rating||0)))}</b></td>
    <td><small>${esc(x.speed||'')}</small></td>
    <td><small>${esc(x.useful||'')}</small></td>
    <td><small>${esc(x.missing||'')}</small></td>
    <td><small>${esc(x.recommend||'')}</small></td></tr>`).join('')||'<tr><td colspan="7"><small>No responses yet.</small></td></tr>';
}
function exportSurveys(){location.href='/api/admin/surveys/export';}
$('who').textContent='Signed in as owner: '+location.host;
refresh();loadSurveys();
</script>
</body>
</html>
"""


@app.route("/")
def root():
    if session.get("uid"):
        return redirect("/chat")
    return AUTH_PAGE


@app.route("/login")
def login():
    if session.get("uid"):
        return redirect("/chat")
    return AUTH_PAGE


@app.route("/logout")
def logout():
    try:
        db.log_activity(session.get("uid"), session.get("email"), "logout", "Signed out")
    except Exception:
        pass
    session.clear()
    return redirect("/")


@app.route("/chat")
@login_required
def chat():
    return PAGE


@app.route("/api/auth", methods=["POST"])
def auth():
    data = request.json or {}
    mode = data.get("mode", "login")
    email = (data.get("email") or "").strip()
    pw = data.get("password") or ""
    if not email or not pw:
        return jsonify({"ok": False, "error": "Email and password are required."})
    if mode == "signup":
        name = (data.get("name") or "").strip() or email.split("@")[0]
        if len(pw) < 4:
            return jsonify({"ok": False, "error": "Password must be at least 4 characters."})
        if db.get_user_by_email(email):
            return jsonify({"ok": False, "error": "That email is already registered. Sign in instead."})
        uid = db.create_user(name, email, hash_pw(pw))
        session["uid"] = uid
        session["name"] = name
        session["email"] = email
        db.log_activity(uid, email, "signup", f"Created account via email (provider: email)")
        return jsonify({"ok": True, "name": name})
    user = db.get_user_by_email(email)
    if not user or not verify_pw(pw, user["password_hash"]):
        return jsonify({"ok": False, "error": "Wrong email or password."})
    session["uid"] = user["id"]
    session["name"] = user["name"]
    session["email"] = user["email"]
    db.log_activity(user["id"], user["email"], "login", "Signed in with email + password")
    return jsonify({"ok": True, "name": user["name"]})


@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    data = request.json or {}
    id_token = (data.get("credential") or "").strip()
    if not id_token:
        return jsonify({"ok": False, "error": "Missing Google credential."})
    info, err = google_verify(id_token)
    if err:
        return jsonify({"ok": False, "error": err})
    email = info["email"].lower()
    name = info.get("name") or email.split("@")[0]
    user = db.get_user_by_email(email)
    if not user:
        # auto-create account on first Google sign-in
        uid = db.create_user(name, email, hash_pw(os.urandom(16).hex() + str(time.time())))
        session["uid"] = uid
        session["name"] = name
        session["email"] = email
        db.log_activity(uid, email, "signup", "Created account via Google Sign-In")
        return jsonify({"ok": True, "name": name, "new": True})
    session["uid"] = user["id"]
    session["name"] = user["name"]
    session["email"] = user["email"]
    db.log_activity(user["id"], email, "login", "Signed in with Google")
    return jsonify({"ok": True, "name": user["name"]})


@app.route("/api/auth/forgot", methods=["POST"])
def forgot():
    """Step 1 of password reset: request a reset link for an email."""
    import secrets
    email = ((request.json or {}).get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "Email is required."})
    user = db.get_user_by_email(email)
    if not user:
        # Do not reveal whether the account exists — same message either way.
        return jsonify({"ok": True, "sent": False, "note": "If that email is registered, a reset link is on its way."})
    token = secrets.token_urlsafe(24)
    db.create_reset_token(user["id"], token)
    link = _reset_link(token)
    sent = _send_reset_email(email, link)
    db.log_activity(user["id"], email, "forgot", f"Password reset requested (email {'sent' if sent else 'returned'})")
    if sent:
        return jsonify({"ok": True, "sent": True, "note": "Reset link sent to your email."})
    # No SMTP configured — hand the link back so the owner can pass it on.
    return jsonify({"ok": True, "sent": False, "link": link, "note": "Reset link (SMTP not configured — share this with the account owner):"})


@app.route("/api/auth/reset", methods=["POST"])
def reset():
    """Step 2 of password reset: use a valid token to set a new password."""
    data = request.json or {}
    token = (data.get("token") or "").strip()
    pw = data.get("password") or ""
    if not token or len(pw) < 4:
        return jsonify({"ok": False, "error": "A token and a password of at least 4 characters are required."})
    row = db.get_reset_token(token)
    if not row or row["used"] or row["expires"] < time.time():
        return jsonify({"ok": False, "error": "This reset link is invalid or has expired. Request a new one."})
    db.consume_reset_token(row["id"])
    db.set_password(row["user_id"], hash_pw(pw))
    user = db.get_user_by_id(row["user_id"])
    db.log_activity(row["user_id"], user["email"] if user else "", "reset", "Password reset completed")
    return jsonify({"ok": True, "note": "Password updated. You can sign in now."})


@app.route("/reset")
def reset_page():
    return RESET_PAGE


# ---- Admin ---------------------------------------------------------------
@app.route("/admin")
@login_required
@owner_required
def admin():
    return ADMIN_PAGE


@app.route("/api/admin/users")
@login_required
@owner_required
def admin_users():
    return jsonify({"ok": True, "users": db.all_users()})


@app.route("/api/admin/activity")
@login_required
@owner_required
def admin_activity():
    return jsonify({"ok": True, "events": db.list_activity(200)})


@app.route("/api/admin/delete-user", methods=["POST"])
@login_required
@owner_required
def admin_delete_user():
    uid = int((request.json or {}).get("uid") or 0)
    if uid == session.get("uid"):
        return jsonify({"ok": False, "error": "You cannot delete your own admin account."})
    db.delete_user(uid)
    _log("admin", f"Deleted user {uid}")
    return jsonify({"ok": True})


@app.route("/api/admin/reset-user-password", methods=["POST"])
@login_required
@owner_required
def admin_reset_user_pw():
    import secrets
    uid = int((request.json or {}).get("uid") or 0)
    user = db.get_user_by_id(uid)
    if not user:
        return jsonify({"ok": False, "error": "User not found."})
    token = secrets.token_urlsafe(24)
    db.create_reset_token(uid, token, ttl_hours=72)
    link = _reset_link(token)
    _log("admin", f"Admin generated reset link for user {uid}")
    return jsonify({"ok": True, "link": link, "email": user["email"]})


@app.route("/api/admin/backup")
@login_required
@owner_required
def admin_backup():
    """Full JSON export — download and keep it in your own cloud storage."""
    data = db.full_backup()
    blob = json.dumps(data, ensure_ascii=False, indent=1, default=str)
    _log("admin", "Exported full backup")
    resp = app.response_class(blob, mimetype="application/json")
    resp.headers["Content-Disposition"] = "attachment; filename=aura-backup.json"
    return resp


@app.route("/api/admin/upgrade", methods=["POST"])
@login_required
@owner_required
def admin_upgrade():
    """Self-upgrade hook: pull the latest code from the GitHub repo (if any)."""
    import subprocess
    repo = ROOT
    if not (repo / ".git").exists():
        return jsonify({"ok": False, "error": "No git repo found on this machine — nothing to pull."})
    try:
        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(repo), capture_output=True, text=True, timeout=90,
        )
        _log("admin", "Ran self-upgrade (git pull)")
        return jsonify({"ok": r.returncode == 0, "out": (r.stdout + r.stderr)[-1200:]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/admin/god", methods=["POST"])
@login_required
@owner_required
def admin_god():
    on = bool((request.json or {}).get("on"))
    config.GOD_MODE = on
    _log("admin", f"Set global God Mode {'ON' if on else 'OFF'}")
    return jsonify({"ok": True, "god": config.GOD_MODE})


@app.route("/api/me")
@login_required
def me():
    return jsonify({
        "name": session.get("name", "User"),
        "level": config.PERMISSION_LEVEL,
        "god": config.GOD_MODE,
        "owner": is_owner(),
    })


@app.route("/api/god", methods=["POST"])
@login_required
def god():
    data = request.json or {}
    config.GOD_MODE = bool(data.get("on"))
    _log("god", f"God Mode {'ON' if config.GOD_MODE else 'OFF'}")
    return jsonify({"god": config.GOD_MODE})


@app.route("/api/chat", methods=["POST"])
@login_required
def chat_api():
    text = (request.json or {}).get("text", "")
    if not text.strip():
        return jsonify({"reply": "", "error": "Empty message."})
    _log("chat", text[:300])
    if not agent.ready:
        return jsonify({"reply": "", "error": "Brain key missing — add GROQ_API_KEY to .env"})
    if _busy.locked():
        return jsonify({"reply": "", "error": "Aura is still busy with your previous message."})
    with _busy:
        reply = agent.chat(text)
    return jsonify({"reply": reply})


@app.route("/api/video/status")
@login_required
def video_status():
    from ..tools import video as video_tool
    return jsonify({"ok": True, **video_tool.status()})


@app.route("/api/video/generate", methods=["POST"])
@login_required
def video_generate():
    data = request.json or {}
    from ..tools import video as video_tool
    result = video_tool.generate(
        prompt=data.get("prompt", ""),
        duration=int(data.get("duration", 6)),
        ratio=data.get("ratio", "16:9"),
    )
    _log("video", f"generate prompt={data.get('prompt','')[:200]}")
    return jsonify(result)


@app.route("/api/video/edit", methods=["POST"])
@login_required
def video_edit():
    data = request.json or {}
    from ..tools import video as video_tool
    result = video_tool.edit(
        prompt=data.get("prompt", ""),
        video_url=data.get("video_url", ""),
    )
    _log("video", f"edit prompt={data.get('prompt','')[:200]}")
    return jsonify(result)


@app.route("/api/approvals")
@login_required
def approvals():
    return jsonify({"approvals": approval.web_pending()})


@app.route("/api/approvals/decide", methods=["POST"])
@login_required
def decide():
    data = request.json or {}
    ok = approval.web_decide(data.get("token", ""), bool(data.get("ok")))
    _log("approval", f"{'Approved' if ok else 'Denied'}: {data.get('token','')[:60]}")
    return jsonify({"ok": ok})


@app.route("/api/audit")
@login_required
def audit():
    return jsonify(db.load_audit(15))


@app.route("/api/activity")
@login_required
def activity():
    """Owner analytics — who did what, per client + recent event stream."""
    if not is_owner():
        return jsonify({"error": "Owner only"}), 403
    return jsonify({"clients": db.client_stats(), "events": db.list_activity(40)})


@app.route("/api/survey", methods=["POST"])
@login_required
def submit_survey():
    try:
        data = request.get_json(force=True) or {}
        rating = int(data.get("rating") or 0)
        if rating < 1 or rating > 5:
            return jsonify({"error": "Rating must be 1-5"}), 400
        db.add_survey(
            user_id=session.get("uid"),
            name=session.get("name", ""),
            email=session.get("email", ""),
            rating=rating,
            speed=str(data.get("speed") or ""),
            useful=str(data.get("useful") or ""),
            missing=str(data.get("missing") or ""),
            recommend=str(data.get("recommend") or ""),
            note=str(data.get("note") or ""),
        )
        db.log_activity(session.get("uid"), session.get("email"), "survey", f"rating={rating}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/surveys")
@owner_required
def admin_surveys():
    return jsonify({"stats": db.survey_stats(), "surveys": db.list_surveys()})


@app.route("/api/admin/surveys/export")
@owner_required
def admin_surveys_export():
    import csv, io

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time", "name", "email", "rating", "speed", "useful", "missing", "recommend", "note"])
    for s in db.list_surveys():
        w.writerow([
            s.get("ts") and __import__("datetime").datetime.fromtimestamp(s["ts"]).strftime("%Y-%m-%d %H:%M"),
            s.get("name") or "", s.get("email") or "", s.get("rating") or "",
            s.get("speed") or "", s.get("useful") or "", s.get("missing") or "",
            s.get("recommend") or "", s.get("note") or "",
        ])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=aura-surveys.csv"})


@app.route("/api/config")
@login_required
def cfg():
    return jsonify({"google_client_id": GOOGLE_CLIENT_ID or "", "owner": session.get("email")})


if __name__ == "__main__":
    db.init_db()
    if not agent.ready:
        print("[Aura] GROQ_API_KEY missing — chat will be offline until added to .env")
    print("Aura web UI: http://127.0.0.1:5173  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5173, debug=False, threaded=True)
