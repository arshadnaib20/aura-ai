"""Nova CLI — main interface. Run with: python -m nova.ui.cli"""
import sys
from pathlib import Path

# make `python -m nova.ui.cli` work from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from .. import config, db
from ..agent import NovaAgent


def print_banner():
    print("=" * 56)
    print("  AURA AI — your audited, approval-gated assistant")
    print(f"  model: {config.MODEL}   level: {config.PERMISSION_LEVEL}" + ("   GOD MODE ON" if config.GOD_MODE else ""))
    print(f"  workspace: {config.WORKSPACE}")
    print("  /exit /notes /audit /stop /level N /god /jobs /help")
    print("=" * 56)


def show_audit(limit=15):
    rows = db.load_audit(limit)
    if not rows:
        print("(audit empty)")
        return
    for r in rows:
        t = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(r["ts"]))
        print(f"  {t} [{r['approved']}] {r['action']} {r['args'][:70]}")


def show_notes():
    rows = db.list_notes(20)
    if not rows:
        print("(no notes)")
        return
    for r in rows:
        print(f"  [{r['id']}] {r['content']}")


def main():
    db.init_db()
    agent = NovaAgent()
    print_banner()

    if not agent.ready:
        print("\n[!] GROQ_API_KEY is missing — chat is offline until you add one.")
        print("    Get a free key at https://console.groq.com, put it in .env,")
        print("    or run:  setx GROQ_API_KEY \"your_key_here\"  then restart.\n")

    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit"):
            print("Bye.")
            break
        elif user_input == "/notes":
            show_notes()
            continue
        elif user_input == "/audit":
            show_audit()
            continue
        elif user_input == "/jobs":
            from ..tools.scheduler import list_jobs
            print(list_jobs())
            continue
        elif user_input == "/stop":
            config.STOP_FILE.write_text("stop", encoding="utf-8")
            print("STOP file created — scheduler and browser jobs will halt.")
            continue
        elif user_input.startswith("/god"):
            config.GOD_MODE = not config.GOD_MODE
            print("GOD MODE " + ("ON — all approvals auto-accepted (still audited)." if config.GOD_MODE else "OFF — approvals required again."))
            continue
        elif user_input.startswith("/level"):
            try:
                lvl = int(user_input.split()[1])
                if 0 <= lvl <= 3:
                    config.PERMISSION_LEVEL = lvl
                    print(f"Permission level -> {lvl}")
                else:
                    print("Level must be 0-3.")
            except Exception:
                print("Usage: /level 0-3")
            continue
        elif user_input == "/help":
            print("/exit /notes /audit /jobs /stop /god /level N")
            continue

        reply = agent.chat(user_input)
        print(f"\nAura> {reply}\n")


if __name__ == "__main__":
    main()
