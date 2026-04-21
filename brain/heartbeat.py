#!/usr/bin/env python3
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "kuun.config")

interval = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
if interval < 5:
    interval = 5

WA_API_PORT = int(os.getenv("WA_API_PORT", "8101"))
JOBS_FILE = PROJECT_ROOT / "brain" / "scheduled_jobs.json"
MEDIA_DIR = PROJECT_ROOT / "media"
ASK_SCRIPT = PROJECT_ROOT / "brain" / "ask_gemini_cli.py"


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_jobs(jobs: list[dict]):
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")


def run_job_query(query: str, job_id: str) -> str:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    output_file = MEDIA_DIR / f"scheduled_{job_id}.txt"

    cmd = ["python3", str(ASK_SCRIPT), query, "--output", str(output_file)]
    try:
        subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=600)
    except subprocess.TimeoutExpired:
        return "Scheduled Gemini job timed out after 10 minutes."
    except Exception as exc:
        return f"Scheduled Gemini job failed: {exc}"

    if output_file.exists():
        try:
            return output_file.read_text(encoding="utf-8").strip() or "Scheduled Gemini job produced empty output."
        except Exception as exc:
            return f"Scheduled Gemini job finished, but output read failed: {exc}"

    return "Scheduled Gemini job finished, but no output file was produced."


def send_whatsapp(to: str, text: str):
    try:
        requests.post(
            f"http://localhost:{WA_API_PORT}/send",
            json={"to": to, "text": text},
            timeout=10,
        )
    except Exception:
        pass


def check_and_run_jobs():
    jobs = load_jobs()
    if not jobs:
        return

    now = datetime.now()
    now_hhmm = now.strftime("%H:%M")
    today = now.strftime("%Y-%m-%d")

    changed = False

    for job in jobs:
        if not job.get("enabled", True):
            continue

        if job.get("time") != now_hhmm:
            continue

        if job.get("last_run_date") == today:
            continue

        sender = job.get("sender")
        query = (job.get("query") or "").strip()
        if not sender or not query:
            job["last_run_date"] = today
            changed = True
            continue

        send_whatsapp(sender, f"⏱️ Running scheduled job `{job.get('id')}` ({job.get('time')})...")
        result = run_job_query(query, job.get("id", "job"))
        send_whatsapp(sender, f"✅ Scheduled job `{job.get('id')}` result:\n{result}")

        job["last_run_date"] = today
        changed = True

    if changed:
        save_jobs(jobs)


while True:
    print(f"[Heartbeat] alive (interval={interval}s)", flush=True)
    check_and_run_jobs()
    time.sleep(interval)
