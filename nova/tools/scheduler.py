"""Scheduler — simple timed jobs stored in SQLite. Runs in a background thread."""
import threading
import time

from .. import config, db


def schedule_job(time_str: str, task: str) -> str:
    """Add a daily job: time_str like '09:00', task is a natural-language instruction."""
    try:
        h, m = time_str.strip().split(":")
        int(h), int(m)
    except Exception:
        return f"Bad time format: {time_str}. Use HH:MM (24h), e.g. 09:00"
    job_id = db.add_job(time_str.strip(), task)
    return f"Scheduled daily job #{job_id} at {time_str}: {task}"


def list_jobs() -> str:
    rows = db.list_jobs()
    if not rows:
        return "No scheduled jobs."
    return "\n".join(
        f"[{r['id']}] {'active' if r['active'] else 'paused'} {r['time']} — {r['task']}"
        for r in rows
    )


def stop_job(job_id: int) -> str:
    db.deactivate_job(job_id)
    return f"Job {job_id} stopped."


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "schedule_job",
        "description": "Schedule a daily job at a time (24h HH:MM). The task is run through the agent loop; risky actions still require approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "Time in 24h format, e.g. '09:00'"},
                "task": {"type": "string", "description": "What to do, e.g. 'summarize my notes'"},
            },
            "required": ["time", "task"],
        },
    },
}


class SchedulerThread:
    """Checks every 30s whether any job is due; runs due jobs via callback."""

    def __init__(self, run_callback, stop_check=None):
        self.run_callback = run_callback
        self.stop_check = stop_check or (lambda: False)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._running = False

    def start(self):
        self._running = True
        self._thread.start()

    def _loop(self):
        last_run = {}  # job_id -> date str
        while self._running:
            if self.stop_check():
                break
            today = time.strftime("%Y-%m-%d")
            try:
                for job in db.list_jobs():
                    if not job["active"]:
                        continue
                    due_time = job["time"]
                    now = time.strftime("%H:%M")
                    if now >= due_time and last_run.get(job["id"]) != today:
                        last_run[job["id"]] = today
                        db.log_audit("scheduler-run", f"job {job['id']}: {job['task']}")
                        try:
                            self.run_callback(job["task"])
                        except Exception as e:
                            db.log_audit("scheduler-error", str(e)[:500])
            except Exception:
                pass
            time.sleep(30)

    def stop(self):
        self._running = False
