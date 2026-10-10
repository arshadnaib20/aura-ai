"""Nova agent loop — Groq brain + tool dispatch + audit + approval gate."""
import json

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
by Groq's free API (api.groq.com) running the Llama-3.1-8B-instant model. You are NOT OpenAI
GPT-4 and NOT Anthropic Claude. Your creator built you as a custom Python agent with its own
tools (files, notes, browser, apps, scheduler, video studio), a SQLite memory and audit log,
an approval gate, and a web UI — hosted on PythonAnywhere. Never claim to be GPT-4, Claude, or
any other model. Never invent your model or provider; if unsure, say you run on Groq/Llama.

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
            db.add_learned_fact(user_id, args.get("fact", "").strip()[:500], source="agent")
            return "Learned and saved to memory. I will remember this from now on."
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
        return f"Unknown tool: {name}"
    except Exception as e:
        db.log_audit(name, f"error: {str(e)[:400]}")
        return f"Tool error: {e}"


class NovaAgent:
    def __init__(self):
        self.client = None
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

        db.save_message("user", user_text)
        history = db.load_messages(history_limit)

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

        for _ in range(8):  # cap tool-call rounds
            try:
                resp = self.client.chat.completions.create(
                    model=config.MODEL,
                    messages=messages,
                    tools=_tool_schemas(),
                    tool_choice="auto",
                    temperature=0.4,
                )
            except Exception as e:
                db.save_message("assistant", f"(error) {e}")
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
                db.save_message("assistant", text)
            return text or "(no reply)"

        return "(stopped after too many tool rounds)"
