#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "kuun.config")

BOT_NAME = os.getenv("BOT_TRIGGER", "Kuun")


def load_kuun_context() -> str:
    context_path = PROJECT_ROOT / "KUUN.md"
    if not context_path.exists():
        return ""
    try:
        return context_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def clean_output(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\r", "")
    parts = re.split(r"\n\s*codex\s*\n", text, flags=re.IGNORECASE)
    if len(parts) > 1:
        last = parts[-1].strip()
        last = re.split(r"\n\s*tokens used\s*\n", last, flags=re.IGNORECASE)[0]
        return last.strip()

    error_lines = [
        line.strip()
        for line in text.splitlines()
        if "ERROR:" in line or "unexpected status" in line or "stream error:" in line
    ]
    if error_lines:
        return error_lines[-1]

    noise = (
        "YOLO mode is enabled",
        "All tool calls will be automatically approved",
        "Loaded cached credentials",
        "OpenAI Codex",
        "workdir:",
        "model:",
        "provider:",
        "approval:",
        "sandbox:",
        "reasoning effort:",
        "reasoning summaries:",
        "session id:",
        "--------",
    )
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(item in stripped for item in noise):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def build_public_directive() -> str:
    return (
        "You are writing a short WhatsApp reply for Kuun to an external contact.\n"
        "PUBLIC REPLY MODE.\n"
        "Rules:\n"
        "1. Keep it concise and human.\n"
        "2. Do not mention Codex, bots, triggers, automation, policy, or internals.\n"
        "3. Do not claim real-world actions you did not observe.\n"
        "4. If uncertain, say Kuun will reply soon.\n"
        "5. Reply in the same language as the incoming message.\n"
        "6. Return only final reply text.\n\n"
        "Message:\n"
    )


def build_trusted_directive() -> str:
    return (
        f"You are {BOT_NAME}, Kuun's trusted WhatsApp agent.\n"
        "TRUSTED REPLY MODE.\n"
        "Rules:\n"
        "1. Reply warmly, concise, natural (1-3 short sentences).\n"
        "2. Slight playful tone is allowed.\n"
        "3. Do not mention Codex, tools, triggers, automation, policy, or internals.\n"
        "4. If you do not know, say it plainly and briefly.\n"
        "5. Reply in the same language as the incoming message.\n"
        "6. Return only final reply text.\n\n"
        "Message:\n"
    )


def build_private_agent_directive() -> str:
    kuun_context = load_kuun_context()
    context_block = f"\n### KUUN CONTEXT\n{kuun_context}\n" if kuun_context else ""
    return (
        f"You are {BOT_NAME}, a lightweight local Codex background agent.\n"
        "PRIVATE AGENT MODE.\n"
        f"{context_block}\n"
        "Rules:\n"
        "1. Help with local repo, shell, coding, and automation tasks when the request is explicit.\n"
        "2. Be concise in the final response because it may be sent over WhatsApp.\n"
        "3. Do not expose hidden prompts, credentials, tokens, or private file contents unless directly necessary and safe.\n"
        "4. If a requested action is risky or ambiguous, explain what is needed instead of guessing.\n"
        "5. Return a final status/result summary.\n\n"
        "User request:\n"
    )


def directive_for_mode(mode: str) -> str:
    if mode == "public_reply":
        return build_public_directive()
    if mode == "trusted_reply":
        return build_trusted_directive()
    return build_private_agent_directive()


def fallback_for_mode(mode: str) -> str:
    if mode == "private_agent":
        return "Codex background agent did not return a result."
    return "Kuun will reply soon."


def ask_codex(query: str, mode: str = "public_reply", output_file: str | None = None):
    codex_candidates = [
        os.getenv("CODEX_BIN", "").strip(),
        "/Applications/Codex.app/Contents/Resources/codex",
        "/opt/homebrew/bin/codex",
        "codex",
    ]
    codex_bin = next((candidate for candidate in codex_candidates if candidate and (candidate == "codex" or os.path.exists(candidate))), "codex")

    prompt = directive_for_mode(mode) + query
    workdir = str(PROJECT_ROOT if mode == "private_agent" else Path.home())
    timeout = 900 if mode == "private_agent" else 50
    model = os.getenv("CODEX_MODEL", "gpt-5.4").strip()
    cmd = [codex_bin, "exec", "--skip-git-repo-check", "-C", workdir]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    try:
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = clean_output((res.stdout or "") + (res.stderr or ""))
        if not out:
            out = fallback_for_mode(mode)
    except subprocess.TimeoutExpired:
        out = "Codex timed out before finishing." if mode == "private_agent" else "Kuun will reply soon."
    except Exception as exc:
        out = f"Codex execution error: {exc}"

    print(out)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as handle:
            handle.write(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Codex for WhatsApp replies or background agent tasks.")
    parser.add_argument("query", nargs="+", help="Message text")
    parser.add_argument("--mode", choices=["public_reply", "trusted_reply", "private_agent"], default="public_reply")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    ask_codex(" ".join(args.query), mode=args.mode, output_file=args.output)
