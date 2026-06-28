#!/usr/bin/env python3
import datetime
import json
import re
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_FILE = PROJECT_ROOT / "brain" / "scheduled_jobs.json"


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_jobs(jobs: list[dict]):
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def normalize_time(value: str) -> str | None:
    raw = value.strip().lower().replace(".", ":")
    hour_match = re.match(r"^(\d{1,2})h$", raw)
    if hour_match:
        hour = int(hour_match.group(1))
        return f"{hour:02d}:00" if 0 <= hour <= 23 else None

    clock_match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if clock_match:
        hour = int(clock_match.group(1))
        minute = int(clock_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def add_job(query: str, schedule_time: str, sender: str = "web_user") -> dict:
    hhmm = normalize_time(schedule_time)
    if not hhmm:
        raise ValueError("Invalid time. Use HH:MM or 13h.")

    jobs = load_jobs()
    job = {
        "id": uuid.uuid4().hex[:8],
        "time": hhmm,
        "query": query,
        "sender": sender,
        "enabled": True,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "last_run_date": None,
    }
    jobs.append(job)
    save_jobs(jobs)
    return job


def list_jobs() -> list[dict]:
    return load_jobs()


def remove_job(job_id: str) -> bool:
    jobs = load_jobs()
    kept = [job for job in jobs if job.get("id") != job_id]
    if len(kept) == len(jobs):
        return False
    save_jobs(kept)
    return True


def check_due(now: datetime.datetime | None = None) -> list[dict]:
    now = now or datetime.datetime.now()
    today = now.date().isoformat()
    due = []
    for job in load_jobs():
        if not job.get("enabled", True):
            continue
        if job.get("last_run_date") == today:
            continue
        if job.get("time") == now.strftime("%H:%M"):
            due.append(job)
    return due


def mark_run(job_id: str, run_date: str | None = None) -> bool:
    jobs = load_jobs()
    changed = False
    for job in jobs:
        if job.get("id") == job_id:
            job["last_run_date"] = run_date or datetime.date.today().isoformat()
            changed = True
            break
    if changed:
        save_jobs(jobs)
    return changed


def format_job(job: dict) -> str:
    status = "on" if job.get("enabled", True) else "off"
    return f"[{job.get('id')}] {job.get('time')} {status} - {job.get('query', '')}"


def usage() -> str:
    return (
        "Usage:\n"
        "  scheduler_tool.py add \"query\" HH:MM [sender]\n"
        "  scheduler_tool.py list\n"
        "  scheduler_tool.py remove <id>\n"
        "  scheduler_tool.py check-due\n"
        "  scheduler_tool.py mark-run <id>"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(usage())
        return 1

    action = argv[1]
    try:
        if action == "add" and len(argv) >= 4:
            job = add_job(argv[2], argv[3], argv[4] if len(argv) > 4 else "web_user")
            print(format_job(job))
            return 0
        if action == "list":
            jobs = list_jobs()
            if not jobs:
                print("(no jobs)")
            else:
                print("\n".join(format_job(job) for job in jobs))
            return 0
        if action == "remove" and len(argv) >= 3:
            print("removed" if remove_job(argv[2]) else "not found")
            return 0
        if action == "check-due":
            print(json.dumps(check_due(), indent=2))
            return 0
        if action == "mark-run" and len(argv) >= 3:
            print("marked" if mark_run(argv[2]) else "not found")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2

    print(usage())
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
