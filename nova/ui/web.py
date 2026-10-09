"""Nova web UI — premium ChatGPT-style interface with login/signup.
Local only. Run: python -m nova.ui.web  then open http://127.0.0.1:5173
"""
import os
import sys
import threading
import time
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
app.secret_key = "nova-local-secret-change-me"

agent = NovaAgent()


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
</style>
</head>
<body>
<div class="card">
<div class="logo"><img src="/nova-logo.png" style="width:54px;height:54px;border-radius:15px;object-fit:cover"></div>
<h1 id="t1">Welcome back</h1>
<div class="sub" id="t2">Sign in to your Nova AI workspace.</div>
<form id="f" onsubmit="go(event)">
<div id="namewrap" style="display:none"><label>Full name</label><input id="name" placeholder="Your name" autocomplete="name"></div>
<label>Email</label><input id="email" placeholder="you@email.com" autocomplete="email" required>
<label>Password</label><input id="pw" type="password" placeholder="••••••••" autocomplete="current-password" required>
<div class="err" id="err"></div>
<button id="b">Sign in</button>
</form>
<div class="alt" id="alt">New here? <a href="#" id="sw" onclick="toggle(event)">Create an account</a></div>
</div>
<script>
let mode='login';
const t1=document.getElementById('t1'),t2=document.getElementById('t2'),b=document.getElementById('b'),
namewrap=document.getElementById('namewrap'),alt=document.getElementById('alt'),sw=document.getElementById('sw');
function toggle(e){e.preventDefault();mode=mode==='login'?'signup':'login';
namewrap.style.display=mode==='signup'?'block':'none';
t1.textContent=mode==='signup'?'Create your account':'Welcome back';
t2.textContent=mode==='signup'?'Start chatting with your personal Nova.':'Sign in to your Nova AI workspace.';
b.textContent=mode==='signup'?'Create account':'Sign in';
alt.innerHTML=mode==='signup'?'Already have one? <a href="#" onclick="toggle(event)">Sign in</a>':'New here? <a href="#" onclick="toggle(event)">Create an account</a>';}
async function go(e){e.preventDefault();const body={mode,email:document.getElementById('email').value,password:document.getElementById('pw').value};
if(mode==='signup')body.name=document.getElementById('name').value;
const r=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const d=await r.json();
if(d.ok){location.href='/chat';}else{document.getElementById('err').textContent=d.error||'Something went wrong';}}
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
        return jsonify({"ok": True, "name": name})
    user = db.get_user_by_email(email)
    if not user or not verify_pw(pw, user["password_hash"]):
        return jsonify({"ok": False, "error": "Wrong email or password."})
    session["uid"] = user["id"]
    session["name"] = user["name"]
    return jsonify({"ok": True, "name": user["name"]})


@app.route("/api/me")
@login_required
def me():
    return jsonify({"name": session.get("name", "User"), "level": config.PERMISSION_LEVEL, "god": config.GOD_MODE})


@app.route("/api/god", methods=["POST"])
@login_required
def god():
    data = request.json or {}
    config.GOD_MODE = bool(data.get("on"))
    return jsonify({"god": config.GOD_MODE})


@app.route("/api/chat", methods=["POST"])
@login_required
def chat_api():
    text = (request.json or {}).get("text", "")
    if not text.strip():
        return jsonify({"reply": "", "error": "Empty message."})
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
    return jsonify({"ok": ok})


@app.route("/api/audit")
@login_required
def audit():
    return jsonify(db.load_audit(15))


if __name__ == "__main__":
    db.init_db()
    if not agent.ready:
        print("[Nova] GROQ_API_KEY missing — chat will be offline until added to .env")
    print("Nova web UI: http://127.0.0.1:5173  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5173, debug=False, threaded=True)
