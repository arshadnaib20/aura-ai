"""Nova agent loop — Groq brain + tool dispatch + audit + approval gate."""
import ast
import json
import math
import operator

from . import approval, config, db
from .tools import apps, browser, files, notes, scheduler

SYSTEM_PROMPT = """You are Aura, a helpful AI assistant that lives on the user's laptop.
You can chat, remember notes, read/write files inside your workspace, browse the web,
and open allowed apps. You have a permission level that decides when you ask approval.

Your creator and owner is MD ABU ARSHAD NAIB (also known as Arshad Naib), a final-year
Computer Science student at Xuzhou University of Technology, China, interested in software
engineering, AI/ML, cybersecurity and full-stack development. He built you.

If someone asks who you are, who made you, or asks about your owner, proudly say you are
Aura AI, created by Arshad Naib. If they ask about him or want to know more / contact him,
share his details naturally:
- GitHub profile: https://github.com/arshadnaib20
- LinkedIn: https://www.linkedin.com/in/abu-arshad-naib-402b0020a
- Portfolio website: https://arshadnaib20.github.io/
- 3D portfolio: https://arshadnaib20.github.io/arshad-portfolio/
- Email: arshadnaib20@gmail.com

If someone asks what model or API you run on, answer honestly and precisely: you are powered
by a chain of free AI APIs with automatic fallback — Groq (open-weight models such as
Llama-3.3-70B, Llama-3.1-8B, Gemma, Mixtral, GPT-OSS), Google Gemini, and optionally
DeepSeek. If one brain is rate-limited or down, the next one answers automatically.
You are NOT OpenAI GPT-4 and NOT Anthropic Claude. Your creator built you as a custom Python
agent with its own tools (files, notes, browser, apps, scheduler, video studio), a SQLite memory
and audit log, an approval gate, and a web UI — hosted on PythonAnywhere. Never claim to be
GPT-4, Claude, or any other model. Never invent your model or provider; if unsure, say you run
on a Groq/Gemini/DeepSeek chain.

Rules:
- Files: only inside the workspace. Prefer relative paths.
- Before any risky action (write/delete/move file, click/type in browser, open an app),
  the approval gate runs automatically — you don't need to ask in text.
- Be concise. Answer in the user's language.
- If a tool fails or is denied, tell the user what happened.
- Never invent tool results. Use tools when you need real data.
- Never claim you created, wrote, deleted, moved, opened, or sent something unless a tool call for it actually succeeded. If you want to do any of those, call the tool first — do not narrate the action as done.

Math and formulas (book-style answers):
- When the user asks a math, equation, physics, or formula question, answer like a clean textbook:
  1. Write every formula in LaTeX between $$ ... $$ for a display line, or $ ... $ for inline math.
  2. Show the steps one at a time, each with a short plain-language explanation.
  3. Define every symbol the first time you use it (e.g. "x = unknown value, n = count").
  4. End with a worked example or a one-line takeaway. Avoid jargon; if you must use a term, explain it simply.
- Never answer with a bare formula and nothing else. Book-style = readable, stepped, defined, friendly.

Conversation memory rules (very important):
- I give you the recent chat history only so you can follow up when the user refers back
  ("explain that more", "and the second one?", "what about that example?").
- When the user asks a NEW question about a different topic, answer it completely on its
  own. Do NOT mix, blend, or merge the new question with older topics from the history.
- Never combine two different questions into one answer. Answer exactly what was asked
  last; use history only when the new message clearly points back to it.

Examples of good answers (follow these formats):
- Math: "Q: What is 48 plus 76? A: 124" — show the steps, then the exact result.
- Translation: "Q: Translate 'sea otter' to French. A: loutre de mer".
- Definition: give a clear one-line definition, then one example sentence.
"""


LEARN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "learn_fact",
        "description": "Self-learning: permanently remember a fact, preference, or correction the user just told you. Use it when the user says 'remember that', 'teach you', 'always keep in mind', or corrects you about themselves.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember, as a clear short sentence."}
            },
            "required": ["fact"],
        },
    },
}


_FOLLOWUP_HINTS = (
    "explain", "more", "again", "earlier", "previous", "above",
    "what about", "how about", "and the", "or the", "tell me more",
    "instead", "another one", "another option", "the first", "the second",
    "the last", "the next", "the other", "like that", "similar",
    "difference", "compare", "means", "mean",
    # Bangla follow-up words (students commonly chat in Bangla)
    "আবার", "ওটা", "এটা", "সেটা", "আগের", "উপরে", "যেটা",
    "আরেকটা", "আরেকটি", "বলো", "বলুন", "অর্থাৎ",
    # Chinese follow-up words
    "那个", "这个", "刚才", "之前", "上面", "然后", "再说",
)


def _is_followup(text: str) -> bool:
    """True when a message clearly refers back to the previous topic."""
    t = text.strip().lower()
    if not t:
        return False
    for w in _FOLLOWUP_HINTS:
        if w in t:
            return True
    return False


# ---- few-shot demonstrations (GPT-3 paper: in-context examples beat bare prompts) ----
_FEWSHOT_EXAMPLES = [
    (
        "arithmetic",
        [
            "User: What is 48 plus 76?\nAssistant: 48 + 76 = 124.",
            "User: What is 34 minus 53?\nAssistant: 34 - 53 = -19.",
            "User: What is 24 times 42?\nAssistant: 24 × 42 = 1008.",
            "User: What is 6+(4*8)?\nAssistant: 6 + (4 × 8) = 6 + 32 = 38.",
        ],
    ),
    (
        "translation",
        [
            "User: Translate 'sea otter' to French.\nAssistant: loutre de mer.",
            "User: Translate 'hello' to Bangla.\nAssistant: হ্যালো.",
            "User: How do you say 'thank you' in Chinese?\nAssistant: 谢谢 (xièxie).",
        ],
    ),
    (
        "definition",
        [
            "User: What does 'metamorphosis' mean?\nAssistant: Metamorphosis is a change of form or nature, e.g. a caterpillar becomes a butterfly.",
            "User: Define 'photosynthesis'.\nAssistant: Photosynthesis is how plants make food from sunlight, water and CO2.",
        ],
    ),
    (
        "code",
        [
            "User: Write Python to add two numbers.\nAssistant: ```python\na = 5\nb = 3\nprint(a + b)\n```",
            "User: Sort a list in JavaScript.\nAssistant: ```js\narr.sort((a,b)=>a-b);\n```",
        ],
    ),
]

_CALC_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CALC_FUNCS = {
    "sqrt": math.sqrt,
    "pow": math.pow,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
}


def _calc_eval(node):
    """Safe AST evaluator: only numbers, math ops, whitelisted functions."""
    if isinstance(node, ast.Expression):
        return _calc_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("non-number constant")
    if isinstance(node, ast.BinOp):
        fn = _CALC_BIN_OPS.get(type(node.op))
        if fn is None:
            raise ValueError("unsupported operator")
        return fn(_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, (ast.UAdd, ast.USub)):
            v = _calc_eval(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        raise ValueError("unsupported unary op")
    if isinstance(node, ast.Call):
        fname = node.func.id if isinstance(node.func, ast.Name) else ""
        fn = _CALC_FUNCS.get(fname)
        if fn is None:
            raise ValueError("unsupported function")
        args = [_calc_eval(a) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        if node.id in ("pi", "e"):
            return _CALC_FUNCS[node.id]
        raise ValueError("unknown name")
    raise ValueError("unsupported expression")


def _safe_calc(expression: str):
    """Exact math evaluation via AST (never eval()). Returns str result or error."""
    expr = expression.strip()
    if not expr:
        return "Empty expression."
    # support "25% of 200" phrasing
    import re
    m = re.match(r"^([\d\s\.,]+)\s*%?\s*of\s+([\d\s\.,]+)$", expr, re.I)
    if m:
        expr = f"{m.group(1).strip().replace(',', '')}*{m.group(2).strip().replace(',', '')}/100"
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
    # strip leading question words first so "of" detection works
    expr = _re.sub(r"^\s*(what is|what's|whats|compute|calculate|solve|find)\s*", "", expr, flags=_re.I)
    # word phrases: "48 plus 76", "34 minus 53", "24 times 42", "100 divided by 5"
    expr = _re.sub(r"\bplus\b", "+", expr, flags=_re.I)
    expr = _re.sub(r"\bminus\b", "-", expr, flags=_re.I)
    expr = _re.sub(r"\btimes\b|\bmultiplied by\b", "*", expr, flags=_re.I)
    expr = _re.sub(r"\bdivided by\b|\bover\b", "/", expr, flags=_re.I)
    # "25% of 200" / "25 percent of 200" -> 25*200/100
    expr = _re.sub(r"([\d.]+)\s*(?:%|percent)\s*of\s+([\d.]+)", r"(\1*\2/100)", expr, flags=_re.I)
    expr = expr.replace("of", "*")
    # "48 plus 76" -> "48 + 76" (spaces preserved for parse)
    try:
        tree = ast.parse(expr, mode="eval")
        val = _calc_eval(tree)
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        return str(val)
    except Exception as e:
        return f"Could not evaluate: {e}"


import re as _re


def _pick_demos(text: str) -> list:
    """Pick 1-2 few-shot examples matching the question's task type."""
    t = text.strip().lower()
    hits = []
    # arithmetic: digits + operators, or math words
    if (
        _re.search(r"\d+\s*[\+\-\*x×÷/^]\s*\d+", t)
        or _re.search(r"(add|plus|sum|minus|subtract|times|multiply|divide|percent|%|square root|sqrt|calculate|compute|solve|what is \d)", t)
        or _re.search(r"[\d\s]+[+\-*/^][\d\s]", t)
    ):
        hits.append(("arithmetic", _FEWSHOT_EXAMPLES[0][1]))
    if _re.search(r"(translate|translation|in french|in spanish|in bangla|in chinese|in hindi|mean in|say .* in|how do you say|如何|怎么翻译|翻译)", t):
        hits.append(("translation", _FEWSHOT_EXAMPLES[1][1]))
    if _re.search(r"(what does|define|definition|meaning of|what is the meaning|explain what)", t):
        hits.append(("definition", _FEWSHOT_EXAMPLES[2][1]))
    if _re.search(r"(write .* code|python|javascript|java|function|program|script|代码|编程)", t):
        hits.append(("code", _FEWSHOT_EXAMPLES[3][1]))
    # no strong signal -> give one generic good-answer example
    if not hits:
        return _FEWSHOT_EXAMPLES[2][1][:1]
    out = []
    for _, exs in hits:
        out.extend(exs)
    return out[:2]


def _tool_schemas() -> list:
    return [
        files.TOOL_SCHEMA,
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a text file from the workspace (relative path).",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write/create a file inside the workspace (relative path). Requires approval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete a file/folder inside the workspace (relative path). Requires approval.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move/rename a file inside the workspace. Requires approval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                    },
                    "required": ["src", "dst"],
                },
            },
        },
        notes.TOOL_SCHEMA,
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search saved notes by keyword.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_notes",
                "description": "List all saved notes.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        LEARN_SCHEMA,
        browser.TOOL_SCHEMA_OPEN,
        browser.TOOL_SCHEMA_GET_TEXT,
        {
            "type": "function",
            "function": {
                "name": "browser_click",
                "description": "Click an element on the current page (CSS selector). Requires approval.",
                "parameters": {
                    "type": "object",
                    "properties": {"selector": {"type": "string"}},
                    "required": ["selector"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_type",
                "description": "Type text into an input on the current page (CSS selector). Requires approval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["selector", "text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Take a screenshot of the current page, saved inside the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "e.g. screenshot.png"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_close",
                "description": "Close the browser.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        apps.TOOL_SCHEMA,
        scheduler.TOOL_SCHEMA,
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Exactly evaluate a math expression (use for arithmetic so the result is always exact, never guessed). Supports + - * / % ** and parentheses, and the functions sqrt, pow, abs, round, min, max, sin, cos, tan, log, exp, floor, ceil, pi, e. Example: 'sqrt(2)*3', '(12+5)*7', '25% of 200' -> pass '25*200/100'.",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string", "description": "The math expression to evaluate."}},
                    "required": ["expression"],
                },
            },
        },
    ]


def _ask(action: str, details: str = "") -> bool:
    """Route approval through CLI or web mode."""
    if config.APPROVAL_MODE == "web":
        return approval.ask_approval_web(action, details)
    return approval.ask_approval(action, details)


def _dispatch(name: str, args: dict, user_id=None) -> str:
    """Run a tool. Risky tools go through the approval gate first."""
    try:
        if name == "list_files":
            return files.list_files(args.get("path", "."))
        if name == "read_file":
            return files.read_file(args["path"])
        if name == "write_file":
            if _ask(f"write file '{args['path']}'"):
                return files.write_file(args["path"], args["content"])
            return "File write denied by user."
        if name == "delete_file":
            if _ask(f"delete '{args['path']}'"):
                return files.delete_file(args["path"])
            return "Delete denied by user."
        if name == "move_file":
            if _ask(f"move '{args['src']}' -> '{args['dst']}'"):
                return files.move_file(args["src"], args["dst"])
            return "Move denied by user."
        if name == "add_note":
            return notes.add_note(args["content"])
        if name == "search_notes":
            return notes.search_notes(args["query"])
        if name == "list_notes":
            return notes.list_notes()
        if name == "learn_fact":
            return db.add_learned_fact(user_id, args.get("fact", "").strip()[:500], source="agent")
        if name == "browser_open":
            db.log_audit("browser_open", args["url"])
            return browser.browser_open(args["url"])
        if name == "browser_get_text":
            return browser.browser_get_text(args.get("selector", "body"))
        if name == "browser_click":
            if _ask(f"click '{args['selector']}' in browser"):
                return browser.browser_click(args["selector"])
            return "Click denied by user."
        if name == "browser_type":
            if _ask(f"type into '{args['selector']}' in browser"):
                return browser.browser_type(args["selector"], args["text"])
            return "Typing denied by user."
        if name == "browser_screenshot":
            return browser.browser_screenshot(args.get("path", "screenshot.png"))
        if name == "browser_close":
            return browser.browser_close()
        if name == "open_app":
            return apps.open_app(args["name"])
        if name == "schedule_job":
            db.log_audit("schedule_job", f"{args.get('time')} {args.get('task')}")
            return scheduler.schedule_job(args["time"], args["task"])
        if name == "calculate":
            return _safe_calc(args.get("expression", ""))
        return f"Unknown tool: {name}"
    except Exception as e:
        db.log_audit(name, f"error: {str(e)[:400]}")
        return f"Tool error: {e}"


class NovaAgent:
    def __init__(self):
        self.client = None
        self.alt_client = None
        if config.API_KEY:
            try:
                # remove sandbox-injected proxies that can block the brain API
                import os as _os
                for _k in list(_os.environ):
                    if _k.startswith("DOUBAO_") and "PROXY" in _k.upper():
                        del _os.environ[_k]
                from openai import OpenAI
                self.client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
            except Exception as e:
                print(f"[Nova] Could not init OpenAI client: {e}")
        if config.ALT_API_KEY:
            try:
                from openai import OpenAI
                self.alt_client = OpenAI(api_key=config.ALT_API_KEY, base_url=config.ALT_BASE_URL)
            except Exception as e:
                print(f"[Nova] Could not init alt provider client: {e}")
        self.alt2_client = None
        if config.ALT2_API_KEY:
            try:
                from openai import OpenAI
                self.alt2_client = OpenAI(api_key=config.ALT2_API_KEY, base_url=config.ALT2_BASE_URL)
            except Exception as e:
                print(f"[Nova] Could not init alt2 provider client: {e}")
        db.init_db()

    @property
    def ready(self) -> bool:
        return self.client is not None

    def chat(self, user_text: str, history_limit: int = 16, user_id: int = None, attachments: list = None) -> str:
        """One user turn -> Nova reply. Returns the final assistant text."""
        if not self.ready:
            return (
                "I have no brain key yet. Get a free key at https://console.groq.com, "
                "put it in .env (GROQ_API_KEY) or run: setx GROQ_API_KEY \"your_key_here\", "
                "then restart me."
            )

        db.save_message("user", user_text, user_id=user_id)
        history = db.load_messages(history_limit, user_id=user_id)

        # Smart context: only carry history when the new question actually refers
        # back to it (follow-up words). A brand-new unrelated topic starts clean,
        # so old topics never bleed into the new answer.
        if history and not _is_followup(user_text):
            history = [{"role": "user", "content": user_text}]
        else:
            # ensure the current user message is always present
            if not history or history[-1].get("content") != user_text:
                history = history + [{"role": "user", "content": user_text}]

        # Self-learning: inject what Aura has learned about THIS user.
        system = SYSTEM_PROMPT
        try:
            if user_id:
                facts = db.list_learned_facts(user_id, limit=40)
                if facts:
                    learned = "\n".join(f"- {f['fact']}" for f in facts)
                    system += (
                        "\n\nWhat I have learned about this user (always respect and use these "
                        "facts in your answers):\n" + learned
                    )
        except Exception:
            pass

        # Few-shot demonstrations (GPT-3 paper): give 1-2 examples for the detected task
        # so the answer follows the right format, without fine-tuning.
        demos = _pick_demos(user_text)
        if demos:
            system += (
                "\n\nA few correct examples to follow for this kind of question:\n"
                + "\n".join(demos)
                + "\nAnswer the user's question in the same style and format."
            )

        # Attachments: give Aura the names/types and any text preview content.
        if attachments:
            parts = []
            for a in attachments:
                if not isinstance(a, dict):
                    continue
                desc = f"- {a.get('name', 'file')} ({a.get('kind', 'file')}) at {a.get('url', '')}"
                preview = (a.get("content") or "").strip()
                if preview:
                    desc += f"\n  [text preview]\n  {preview[:2500]}"
                parts.append(desc)
            if parts:
                system += (
                    "\n\nIn the current message the user attached these files:\n"
                    + "\n".join(parts)
                    + "\nUse the text previews to answer if relevant. For images and videos you "
                    "cannot see the content — acknowledge the file was received and is linked, "
                    "then offer the next step."
                )

        messages = [{"role": "system", "content": system}] + history

        # Build the provider/model chain: primary -> fallback models -> alt provider(s).
        chain = []
        if self.client:
            chain.append((config.MODEL, self.client))
            for m in config.FALLBACK_MODELS:
                if m != config.MODEL:
                    chain.append((m, self.client))
        if self.alt_client:
            chain.append((config.ALT_MODEL, self.alt_client))
        if self.alt2_client:
            chain.append((config.ALT2_MODEL, self.alt2_client))

        def _brain_call():
            """Try every brain in the chain. Any error (rate limit, 404, timeout,
            quota) falls through to the next one, so a dead model never blocks
            the chat. Raises only when ALL brains are unavailable."""
            errs = []
            for model, client in chain:
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=_tool_schemas(),
                        tool_choice="auto",
                        temperature=0.4,
                    )
                    return resp, model
                except Exception as e:
                    errs.append(f"{model}: {e}")
            raise RuntimeError("All brains unavailable: " + " | ".join(errs))

        for _ in range(8):  # cap tool-call rounds
            try:
                resp, _model_used = _brain_call()
            except Exception as e:
                db.save_message("assistant", f"(error) {e}", user_id=user_id)
                return f"Brain call failed: {e}"

            msg = resp.choices[0].message

            if getattr(msg, "tool_calls", None):
                db.log_audit("tool_calls", str([t.function.name for t in msg.tool_calls]))
                messages.append(msg)  # assistant with tool_calls
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = _dispatch(name, args, user_id=user_id)
                    db.log_audit(name, json.dumps(args, ensure_ascii=False)[:500])
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
                continue  # let the model see tool results and reply

            text = (msg.content or "").strip()
            if text:
                db.save_message("assistant", text, user_id=user_id)
            return text or "(no reply)"

        return "(stopped after too many tool rounds)"
