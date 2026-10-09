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

from flask import Flask, jsonify, request, session, redirect, send_file, send_from_directory

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
            "Hello,\n\nSomeone asked to reset the password for your Nova AI account "
            f"({email}). If that was you, open the link below within 24 hours:\n\n{reset_url}\n\n"
            "If you did not ask for this, you can ignore this email.\n\n— Nova AI",
            "plain",
            "utf-8",
        )
        msg["Subject"] = "Nova AI — reset your password"
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
<title>Nova AI</title>
<link rel="icon" href="/nova-logo.png">
<style>
:root{--bg:#050505;--bg2:#0A0A0C;--gold:#C9A961;--gold2:#E5CD8E;--txt:#EDEAE2;--dim:#8A8678;--line:#1E1E22;--ok:#5EC8A5;--no:#E06666}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;height:100vh;display:flex;overflow:hidden}
.side{width:260px;background:var(--bg2);border-right:1px solid var(--line);display:flex;flex-direction:column;flex-shrink:0}
.brand{display:flex;align-items:center;gap:10px;padding:18px 16px;border-bottom:1px solid var(--line)}
.brand .dot{width:30px;height:30px;border-radius:8px;background:radial-gradient(circle at 30% 30%,#E5CD8E,#C9A961 60%,#8a733a);display:flex;align-items:center;justify-content:center;font-weight:800;color:#111}
.brand h1{font-size:15px;letter-spacing:.18em;font-weight:700}
.brand small{display:block;color:var(--dim);font-size:10px;letter-spacing:.08em}
.newbtn{margin:14px;padding:12px;border-radius:12px;border:1px solid var(--line);background:transparent;color:var(--txt);cursor:pointer;font-size:13px;transition:.2s}
.newbtn:hover{border-color:var(--gold);color:var(--gold)}
.mid{flex:1;display:flex;flex-direction:column}
.top{padding:16px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--dim)}
.top b{color:var(--txt)}
.acc{display:flex;align-items:center;gap:8px}
.acc .av{width:28px;height:28px;border-radius:50%;background:var(--gold);color:#111;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px}
a.logout{color:var(--dim);text-decoration:none;font-size:12px}
a.logout:hover{color:var(--no)}
.chat{flex:1;overflow-y:auto;padding:28px 8px;display:flex;flex-direction:column;gap:20px}
.wrap{max-width:760px;margin:0 auto;width:100%;display:flex;flex-direction:column;gap:20px}
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
@media(max-width:720px){.side{display:none}}
</style>
</head>
<body>
<div class="side">
  <div class="brand"><img src="/nova-logo.png" style="width:34px;height:34px;border-radius:8px;object-fit:cover"><div><h1>NOVA AI</h1><small>YOUR LOCAL ASSISTANT</small></div></div>
  <button class="newbtn" onclick="newChat()">+ New chat</button>
  <button class="newbtn" onclick="showClients()">Clients · activity</button>
  <button class="newbtn" id="adminbtn" style="display:none" onclick="location.href='/admin'">Admin panel</button>
  <div style="padding:14px;font-size:11px;color:var(--dim);line-height:1.7;border-top:1px solid var(--line);margin-top:auto">
    Level <span id="lvl"></span> · every risky action asks you first.<br>All actions are audited.
    <div style="display:flex;align-items:center;justify-content:space-between;margin-top:12px">
      <span style="letter-spacing:.08em">GOD MODE</span>
      <label class="sw"><input type="checkbox" id="god" onchange="setGod(this.checked)"><span></span></label>
    </div>
  </div>
</div>
<div class="mid">
  <div class="top"><b id="who"></b><div class="acc"><div class="av" id="av"></div><a class="logout" href="/logout">Sign out</a></div></div>
  <div class="chat" id="chat"></div>
  <div style="border-top:1px solid var(--line);padding:14px">
    <div class="bar"><button class="mic" id="mic" onclick="toggleMic()" title="Voice input"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="22"/></svg></button><input class="in" id="inp" placeholder="Ask Nova anything..." autocomplete="off"><button class="send" id="btn">Send</button></div>
  </div>
  <canvas id="orb"></canvas>
</div>
<script>
const chat=document.getElementById('chat'),inp=document.getElementById('inp'),btn=document.getElementById('btn');
let hist=[];
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function addMsg(role,text){
  const w=document.createElement('div');w.className='wrap';
  const m=document.createElement('div');m.className='m '+role;
  m.innerHTML=(role==='u'?'<div class="ic">YOU</div>':'<div class="ic">N</div>')+'<div class="body">'+esc(text)+'</div>';
  w.appendChild(m);chat.appendChild(w);chat.scrollTop=chat.scrollHeight;return w;
}
function addTyping(){const w=document.createElement('div');w.className='wrap';w.innerHTML='<div class="m n"><div class="ic">N</div><div class="body"><span class="typing"><span></span><span></span><span></span></span></div></div>';chat.appendChild(w);chat.scrollTop=chat.scrollHeight;return w;}
async function send(){
  const v=inp.value.trim();if(!v||btn.disabled)return;
  inp.value='';btn.disabled=true;addMsg('u',v);
  const t=addTyping();orbEnergy=1;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:v})});
    const d=await r.json();
    t.remove();orbEnergy=0.6;
    if(d.reply)addMsg('n',d.reply);
    if(d.error)addMsg('n','Error: '+d.error);
    pollApprovals();
  }catch(e){t.remove();orbEnergy=0.3;addMsg('n','Network error: '+e);}
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
function newChat(){hist=[];chat.innerHTML='';chat.appendChild(emptyHTML());inp.focus();}
async function showClients(){
  chat.innerHTML='';
  const w=document.createElement('div');w.className='wrap';
  w.innerHTML='<div class="empty"><div class="logo">N</div><h2>Client activity</h2><p>Loading who did what…</p></div>';
  chat.appendChild(w);chat.scrollTop=chat.scrollHeight;
  try{
    const r=await fetch('/api/activity');const d=await r.json();
    let html='<div class="wrap"><div class="empty" style="padding-top:6vh"><div class="logo">N</div><h2>Clients · who did what</h2></div>';
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
  d.innerHTML=`<div class="empty"><div class="logo">N</div><h2>How can I help you?</h2>
  <p>I can manage files, remember notes, browse the web, open apps and run scheduled jobs.<br>Risky actions always ask for your approval first.</p>
  <div class="sug"><button onclick="q('List my files in the workspace')">List my files</button><button onclick="q('Save a note: remember this')">Save a note</button><button onclick="q('Open Wikipedia and summarize the front page')">Browse the web</button><button onclick="q('What can you do?')">What can you do?</button></div></div>`;
  return d;
}
function q(t){inp.value=t;send();}
async function setGod(on){
  await fetch('/api/god',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on})});
  pollApprovals();
}
async function me(){const r=await fetch('/api/me');const d=await r.json();
  document.getElementById('who').textContent=d.name;document.getElementById('av').textContent=d.name[0].toUpperCase();
  document.getElementById('lvl').textContent=d.level;
  document.getElementById('god').checked=!!d.god;
  document.title='Nova AI — '+d.name;
  if(d.owner){document.getElementById('adminbtn').style.display='block';}
}
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
btn.addEventListener('click',send);
me();chat.appendChild(emptyHTML());
setInterval(pollApprovals,2500);inp.focus();

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
<title>Nova AI</title>
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
<div class="sub" id="t2">Sign in to your Nova AI workspace.</div>
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
t2.textContent=mode==='signup'?'Start chatting with your personal Nova.':'Sign in to your Nova AI workspace.';
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
<title>Nova AI — Reset password</title>
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
<div class="sub">Choose a new password for your Nova AI account.</div>
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
<title>Nova AI — Admin</title>
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
  <h1>NOVA ADMIN</h1>
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
  a.download='nova-backup.json';
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
$('who').textContent='Signed in as owner: '+location.host;
refresh();
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
    resp.headers["Content-Disposition"] = "attachment; filename=nova-backup.json"
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
        return jsonify({"reply": "", "error": "Nova is still busy with your previous message."})
    with _busy:
        reply = agent.chat(text)
    return jsonify({"reply": reply})


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
    return jsonify({"clients": db.client_stats(), "events": db.list_activity(40)})


@app.route("/api/config")
@login_required
def cfg():
    return jsonify({"google_client_id": GOOGLE_CLIENT_ID or "", "owner": session.get("email")})


if __name__ == "__main__":
    db.init_db()
    if not agent.ready:
        print("[Nova] GROQ_API_KEY missing — chat will be offline until added to .env")
    print("Nova web UI: http://127.0.0.1:5173  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5173, debug=False, threaded=True)
