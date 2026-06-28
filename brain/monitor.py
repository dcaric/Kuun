#!/usr/bin/env python3
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from google import genai

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "kuun.config")

BASE_URL = os.getenv("REMOTE_BRIDGE_URL", "http://localhost:8100")
AUTH_TOKEN = os.getenv("BRIDGE_SECRET_KEY", "default-secret-key")
BOT_TRIGGER = os.getenv("BOT_TRIGGER", "kuun")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2"))
if POLL_INTERVAL < 0.5:
    POLL_INTERVAL = 0.5

JOBS_FILE = PROJECT_ROOT / "brain" / "scheduled_jobs.json"
KUUN_CLI = PROJECT_ROOT / "kuun"
ACTIVE_GEMINI_JOBS = {}
WHITELIST_FILE = PROJECT_ROOT / "whitelist.json"
CONTACTS_CACHE_FILE = PROJECT_ROOT / "contacts_cache.json"
ALLOWED_NUMBERS_FILE = PROJECT_ROOT / "allowed_numbers.txt"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = None
if GOOGLE_API_KEY:
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
    except Exception as e:
        print(f"❌ Failed to init google-genai Client: {e}", flush=True)


def report_status(task_id: str, message: str):
    try:
        requests.post(
            f"{BASE_URL}/status-update",
            json={"id": task_id, "message": message},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            timeout=5,
        )
    except Exception:
        pass


def report_result(task_id: str, output: str):
    try:
        requests.post(
            f"{BASE_URL}/report-result",
            json={"id": task_id, "output": output},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            timeout=5,
        )
    except Exception:
        pass


def load_whitelist() -> dict[str, str]:
    if not WHITELIST_FILE.exists():
        return {}
    try:
        data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out: dict[str, str] = {}
            for k, v in data.items():
                key = str(k).strip()
                val = str(v).strip()
                if key and val:
                    out[key] = val
            return out
        if isinstance(data, list):
            # Backward compatibility: upgrade list format to key=value mapping.
            out: dict[str, str] = {}
            for x in data:
                s = str(x).strip()
                if s:
                    out[s] = s
            return out
    except Exception:
        pass
    return {}


def save_whitelist(items: dict[str, str]):
    WHITELIST_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


def is_system_user(sender_jid: str, from_me: bool = False) -> bool:
    if from_me:
        return True
    if not sender_jid:
        return False

    phone = re.sub(r"\D", "", str(sender_jid).split("@")[0].split(":")[0])
    if not phone:
        return False

    try:
        if not ALLOWED_NUMBERS_FILE.exists():
            return False
        nums = {
            re.sub(r"\D", "", line.strip())
            for line in ALLOWED_NUMBERS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        return phone in nums
    except Exception:
        return False


def is_contact_allowed(push_name: str, sender_jid: str, from_me: bool) -> bool:
    entries = load_whitelist()
    if not entries:
        return False
    if from_me:
        return False
    sender_lower = (sender_jid or "").lower().strip()
    sender_core = sender_lower.split("@")[0].split(":")[0]
    sender_digits = re.sub(r"\D", "", sender_core)
    for key in entries.keys():
        k = str(key or "").lower().strip()
        if not k:
            continue
        k_core = k.split("@")[0].split(":")[0]
        k_digits = re.sub(r"\D", "", k_core)
        if sender_lower == k or sender_core == k_core:
            return True
        if sender_digits and k_digits and sender_digits == k_digits:
            return True
    return False


def load_revan_personality() -> str:
    skill_path = PROJECT_ROOT / ".agent" / "skills" / "revan_personality" / "SKILL.md"
    if skill_path.exists():
        try:
            return skill_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return (
        "Revan is warm, witty, concise, and replies in the user's language. "
        "Keep answers short and natural. End trusted replies with: 🤖 [AI Revan]"
    )


def safe_conversational_reply(instruction: str, mode: str, media_paths=None) -> str:
    text = (instruction or "").strip()

    # For trusted chats, if Gemini is available, use it directly!
    if mode == "trusted_chat" and client:
        personality = load_revan_personality()
        prompt = f"""
You are Revan, Dario's agent, replying in a trusted WhatsApp chat.
Do NOT prefix your response with your name or "AI Revan:". Just output the raw message text.

{personality}

Message:
{text}
""".strip()
        
        try:
            uploaded_files = []
            if media_paths:
                for path in media_paths:
                    if path and os.path.exists(path):
                        try:
                            print(f"📂 Processing Media for Chat: {path}", flush=True)
                            uploaded_files.append(client.files.upload(file=path))
                        except Exception as e:
                            print(f"⚠️ Error uploading media: {path}: {e}", flush=True)

            contents = [prompt]
            if uploaded_files:
                contents = uploaded_files + [prompt]

            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=contents
            )
            answer = (response.text or "").strip()
            if answer:
                # Strip prefixes if any
                answer = re.sub(r"^(AI\s*)?Revan:\s*", "", answer, flags=re.IGNORECASE)
                return answer
        except Exception as e:
            print(f"⚠️ Gemini direct reply failed: {e}", flush=True)

    if not text:
        return "Dario will reply soon."

    if mode == "trusted_chat":
        personality = load_revan_personality()
        prompt = f"{personality}\n\nMessage:\n{text}"
        codex_out = codex_restricted_reply(prompt, mode="trusted_reply")
    else:
        codex_out = codex_restricted_reply(text, mode="public_reply")

    if not codex_out:
        codex_out = "Dario will reply soon."
    return codex_out


def codex_restricted_reply(instruction: str, mode: str = "public_reply") -> str:
    query = (instruction or "").strip()
    if not query:
        return "Dario will reply soon."

    script_path = PROJECT_ROOT / "brain" / "ask_codex.py"
    py = "python3"
    try:
        proc = subprocess.run(
            [py, str(script_path), query, "--mode", mode],
            capture_output=True,
            text=True,
            timeout=50,
            stdin=subprocess.DEVNULL,
            cwd=str(PROJECT_ROOT),
        )
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if not out or out.startswith("Error:"):
            return "Dario will reply soon."
        return out
    except Exception:
        return "Dario will reply soon."


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


def normalize_time(value: str) -> str | None:
    raw = value.strip().lower().replace(".", ":")

    m = re.match(r"^(\d{1,2})h$", raw)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
        return None

    m = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None


def parse_gemini_query(instruction: str) -> str | None:
    if not instruction:
        return None
    text = instruction.strip()

    if re.match(r"^-\s+", text):
        return re.sub(r"^-\s+", "", text).strip()

    if re.match(r"^g\s+", text, flags=re.IGNORECASE):
        return re.sub(r"^g\s+", "", text, flags=re.IGNORECASE).strip()

    if re.match(r"^ask\s+geminicli\s*[-:]\s*", text, flags=re.IGNORECASE):
        return re.sub(r"^ask\s+geminicli\s*[-:]\s*", "", text, flags=re.IGNORECASE).strip()

    return None


def build_help_message() -> str:
    return (
        "✅ Result:\n"
        "🚀 *KUUN CAPABILITIES*\n"
        "Minimal WhatsApp bridge for Gemini CLI\n\n"
        "♊ GEMINI BACKGROUND TASKS\n"
        f"• Ask Gemini from WhatsApp: `{BOT_TRIGGER} - <question>`\n"
        f"• Shortcut format: `{BOT_TRIGGER} g <question>`\n"
        "• Kuun runs Gemini in background and sends final reply when done\n\n"
        "⏱️ KUUN SCHEDULER\n"
        f"• `{BOT_TRIGGER} set job which will at 13h check weather in Split`\n"
        f"• `{BOT_TRIGGER} list jobs`\n"
        f"• `{BOT_TRIGGER} remove the scheduled job with ID abc12345`\n\n"
        "⚙️ SYSTEM COMMANDS\n"
        f"• `{BOT_TRIGGER} status`\n"
        f"• `{BOT_TRIGGER} help`\n"
        f"• `{BOT_TRIGGER} restart`\n\n"
        "✅ CONVERSATIONAL ALLOWED LIST (WHATSAPP)\n"
        f"• `{BOT_TRIGGER} whitelist add <name>`\n"
        f"• `{BOT_TRIGGER} whitelist remove <name>`\n"
        f"• `{BOT_TRIGGER} whitelist`\n\n"
        "🏢 GROUP ALLOWED LIST (WHATSAPP)\n"
        f"• `{BOT_TRIGGER} whitelist group add <id-or-name>`\n"
        f"• `{BOT_TRIGGER} whitelist group remove <id-or-name>`\n"
        f"• `{BOT_TRIGGER} whitelist group`\n\n"
        "🔒 WHITELIST (CLI)\n"
        "• `kuun add-number <num>`\n"
        "• `kuun remove-number <num>`\n"
        "• `kuun users`\n\n"
        "🔧 SERVICE COMMANDS (CLI)\n"
        "• `kuun start`\n"
        "• `kuun stop`\n"
        "• `kuun restart`\n"
        "• `kuun status`\n"
        "• `kuun whatsapp link`\n\n"
        f"💡 Try: `{BOT_TRIGGER} - what time is it in Zagreb?`"
    )


def scheduler_set(instruction: str, sender: str) -> str | None:
    m = re.match(r"(?i)^set\s+job\s+which\s+will\s+at\s+(.+?)\s+check\s+(.+)$", instruction.strip())
    if not m:
        return None

    schedule_time_raw = m.group(1).strip()
    check_query = m.group(2).strip()
    hhmm = normalize_time(schedule_time_raw)

    if not hhmm:
        return "⚠️ Invalid time format. Use `13h` or `13:00`."

    jobs = load_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs.append(
        {
            "id": job_id,
            "time": hhmm,
            "query": check_query,
            "sender": sender,
            "enabled": True,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "last_run_date": None,
        }
    )
    save_jobs(jobs)

    return f"✅ Job created.\nID: {job_id}\nTime: {hhmm}\nTask: {check_query}"


def scheduler_list(instruction: str) -> str | None:
    text = instruction.strip().lower()
    accepted = {
        "list all scheduled jobs",
        "list scheduled jobs",
        "list all jobs",
        "list jobs",
    }
    if text not in accepted:
        return None

    jobs = [j for j in load_jobs() if j.get("enabled", True)]
    if not jobs:
        return "✅ Result:\n📅 *Scheduled Jobs:*\n\n(no jobs active)"

    lines = ["✅ Result:", "📅 *Scheduled Jobs:*", ""]
    for j in jobs:
        jid = j.get("id", "unknown")
        jtime = j.get("time", "--:--")
        jquery = j.get("query", "(no query)")
        last_run = j.get("last_run_date")
        lines.append(f"[{jid}] {jtime} - 📄 {jquery}")
        if last_run:
            lines.append(f"   └─ 🔄 {last_run} ✅")
    return "\n".join(lines)


def scheduler_remove(instruction: str) -> str | None:
    text = instruction.strip()
    m = re.match(r"(?i)^remove\s+the\s+scheduled\s+job\s+with\s+id\s+([a-zA-Z0-9_-]+)$", text)
    if not m:
        m = re.match(r"(?i)^remove\s+job\s+([a-zA-Z0-9_-]+)$", text)
    if not m:
        return None

    job_id = m.group(1)
    jobs = load_jobs()
    new_jobs = [j for j in jobs if j.get("id") != job_id]
    if len(new_jobs) == len(jobs):
        return f"⚠️ Job `{job_id}` not found."

    save_jobs(new_jobs)
    return f"✅ Removed scheduled job `{job_id}`."


def trigger_service_restart(task_id: str):
    report_result(task_id, "♻️ Restarting Kuun services...")
    # Use /bin/sh for Linux/macOS compatibility.
    cmd = f"sleep 1; '{KUUN_CLI}' restart >/dev/null 2>&1"
    subprocess.Popen(["/bin/sh", "-lc", cmd], cwd=str(PROJECT_ROOT))


def spawn_gemini_job(task_id: str, query: str):
    output_file = PROJECT_ROOT / "media" / f"gemini_{task_id}.txt"
    cmd = [
        "python3",
        str(PROJECT_ROOT / "brain" / "ask_gemini_cli.py"),
        query,
        "--output",
        str(output_file),
    ]
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
    ACTIVE_GEMINI_JOBS[task_id] = {
        "task_id": task_id,
        "process": proc,
        "output_file": output_file,
    }


def process_task(task: dict):
    task_id = task["id"]
    instruction = (task.get("instruction") or "").strip()
    instruction_norm = re.sub(r"\s+", " ", instruction).strip()
    instruction_lower = instruction_norm.lower()
    sender = task.get("sender", "")
    push_name = (task.get("pushName") or "").strip()
    task_mode = (task.get("mode") or "agent").strip()
    query = parse_gemini_query(instruction)
    from_me = bool(task.get("fromMe", False))

    if task_mode == "agent" and not is_system_user(sender, from_me=from_me):
        return

    if instruction_lower.startswith("whitelist add "):
        name_to_add = instruction_norm[14:].strip()
        if not name_to_add:
            report_result(task_id, "⚠️ Usage: whitelist add <name>")
            return
        items = load_whitelist()
        resolved_jid = None
        if CONTACTS_CACHE_FILE.exists():
            try:
                contacts = json.loads(CONTACTS_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(contacts, dict):
                    target = name_to_add.lower().strip()
                    for jid, cname in contacts.items():
                        c = str(cname).lower().strip()
                        if target and c and target in c:
                            resolved_jid = str(jid)
                            break
            except Exception:
                pass

        if resolved_jid:
            items[resolved_jid] = name_to_add
            report_result(task_id, f"✅ Resolved '{name_to_add}' to {resolved_jid.split('@')[0]} and added to whitelist.")
        else:
            items[name_to_add] = name_to_add
            report_result(task_id, f"✅ Added '{name_to_add}' to whitelist (number not resolved yet).")
        save_whitelist(items)
        return

    if instruction_lower.startswith("whitelist remove "):
        name_to_remove = instruction_norm[17:].strip()
        if not name_to_remove:
            report_result(task_id, "⚠️ Usage: whitelist remove <name>")
            return
        items = load_whitelist()
        target = name_to_remove.lower().strip()
        removed_key = None
        for k, v in items.items():
            if target in str(k).lower() or target in str(v).lower():
                removed_key = k
                break
        if removed_key is not None:
            removed_val = items.pop(removed_key)
            save_whitelist(items)
            report_result(
                task_id,
                f"✅ Removed '{removed_val}' ({str(removed_key).split('@')[0]}) from the allowed contacts list.",
            )
            return
        report_result(task_id, f"⚠️ '{name_to_remove}' not found in allowed contacts list.")
        return

    if instruction_lower == "whitelist":
        items = load_whitelist()
        if items:
            lines = []
            for k, v in items.items():
                key_txt = str(k)
                num = key_txt.split("@")[0] if "@" in key_txt else "name"
                lines.append(f"- {v} ({num})")
            report_result(task_id, "✅ *Allowed Contacts (Whitelist)*\n" + "\n".join(lines))
        else:
            report_result(task_id, "⚠️ Whitelist is empty! Revan will NOT answer anyone.")
        return

    if re.match(r"(?i)^whitelist\s+groups?\s+add\s+", instruction_norm):
        group_to_add = re.sub(r"(?i)^whitelist\s+groups?\s+add\s+", "", instruction_norm).strip()
        if not group_to_add:
            report_result(task_id, "⚠️ Usage: whitelist group add <id-or-name>")
            return
        groups_file = PROJECT_ROOT / "whitelist_groups.json"
        groups = []
        if groups_file.exists():
            try:
                data = json.loads(groups_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    groups = [str(x) for x in data]
            except Exception:
                pass
        if group_to_add not in groups:
            groups.append(group_to_add)
            groups_file.write_text(json.dumps(groups, indent=2), encoding="utf-8")
        report_result(task_id, f"✅ Added group '{group_to_add}' to the allowed groups list.")
        return

    if re.match(r"(?i)^whitelist\s+groups?\s+remove\s+", instruction_norm):
        group_to_remove = re.sub(r"(?i)^whitelist\s+groups?\s+remove\s+", "", instruction_norm).strip()
        if not group_to_remove:
            report_result(task_id, "⚠️ Usage: whitelist group remove <id-or-name>")
            return
        groups_file = PROJECT_ROOT / "whitelist_groups.json"
        groups = []
        if groups_file.exists():
            try:
                data = json.loads(groups_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    groups = [str(x) for x in data]
            except Exception:
                pass
        lowered = [g.lower() for g in groups]
        if group_to_remove.lower() in lowered:
            idx = lowered.index(group_to_remove.lower())
            removed = groups.pop(idx)
            groups_file.write_text(json.dumps(groups, indent=2), encoding="utf-8")
            report_result(task_id, f"✅ Removed group '{removed}' from the allowed groups list.")
        else:
            report_result(task_id, f"⚠️ Group '{group_to_remove}' not found in allowed groups list.")
        return

    if re.match(r"(?i)^whitelist\s+groups?$", instruction_norm):
        groups_file = PROJECT_ROOT / "whitelist_groups.json"
        groups = []
        if groups_file.exists():
            try:
                data = json.loads(groups_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    groups = [str(x) for x in data]
            except Exception:
                pass
        if groups:
            report_result(task_id, "🏢 *Allowed Groups (Whitelist)*\n" + "\n".join(f"- {g}" for g in groups))
        else:
            report_result(task_id, "🏢 No groups whitelisted. Group messages are ignored by default.")
        return

    if task_mode in {"public_chat", "trusted_chat"}:
        if from_me:
            return
        if not is_contact_allowed(push_name, sender, from_me):
            return
        media_paths = task.get("media_paths") or ([task.get("media_path")] if task.get("media_path") else [])
        report_result(task_id, safe_conversational_reply(instruction, task_mode, media_paths=media_paths))
        return

    if query:
        report_status(task_id, "♊ GeminiCLI job started in background. I will send the result when it finishes.")
        spawn_gemini_job(task_id, query)
        return

    sched_result = scheduler_set(instruction, sender)
    if sched_result:
        report_result(task_id, sched_result)
        return

    sched_result = scheduler_list(instruction)
    if sched_result:
        report_result(task_id, sched_result)
        return

    sched_result = scheduler_remove(instruction)
    if sched_result:
        report_result(task_id, sched_result)
        return

    if instruction_lower in {"restart", "kuun restart"}:
        trigger_service_restart(task_id)
        return

    if instruction_lower in {"help", "kuun help"}:
        report_result(task_id, build_help_message())
        return

    if instruction_lower in {"status", "system status", "kuun status"}:
        report_result(task_id, "📊 Kuun is active. FastAPI, WhatsApp bridge, monitor, and heartbeat should be running.")
        return

    report_result(
        task_id,
        "Use `kuun - <question>` or `kuun g <question>` to run GeminiCLI in background.",
    )


def check_finished_jobs():
    done = []
    for task_id, job in ACTIVE_GEMINI_JOBS.items():
        proc = job["process"]
        if proc.poll() is None:
            continue

        output_file = job["output_file"]
        result_text = "GeminiCLI finished, but no output file was produced."
        if output_file.exists():
            try:
                result_text = output_file.read_text(encoding="utf-8").strip() or result_text
            except Exception as exc:
                result_text = f"GeminiCLI finished, but output read failed: {exc}"

        report_result(task_id, result_text)
        done.append(task_id)

    for task_id in done:
        ACTIVE_GEMINI_JOBS.pop(task_id, None)


def main_loop():
    print(f"[Monitor] started (poll={POLL_INTERVAL}s)", flush=True)
    while True:
        check_finished_jobs()
        try:
            resp = requests.get(
                f"{BASE_URL}/get-task",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
                timeout=10,
            )
            if resp.status_code == 200:
                task = resp.json()
                if task and task.get("id"):
                    process_task(task)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main_loop()
