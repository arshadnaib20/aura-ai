"""Notes tools — saved to SQLite."""
from .. import db


def add_note(content: str) -> str:
    db.add_note(content)
    return "Note saved."


def search_notes(query: str) -> str:
    rows = db.search_notes(query)
    if not rows:
        return "No notes found."
    return "\n".join(f"[{r['id']}] {r['content']}" for r in rows)


def list_notes() -> str:
    rows = db.list_notes(limit=50)
    if not rows:
        return "No notes yet."
    return "\n".join(f"[{r['id']}] {r['content']}" for r in rows)


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_note",
        "description": "Save a note to memory (SQLite). Use for facts, tasks, ideas the user wants remembered.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The note text to save"}
            },
            "required": ["content"],
        },
    },
}
