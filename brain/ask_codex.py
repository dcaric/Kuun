#!/usr/bin/env python3
import argparse
import os
import re
import subprocess


def clean_output(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\r", "")
    parts = re.split(r"\n\s*codex\s*\n", text, flags=re.IGNORECASE)
    if len(parts) > 1:
        last = parts[-1].strip()
        last = re.split(r"\n\s*tokens used\s*\n", last, flags=re.IGNORECASE)[0]
        return last.strip()

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
        "session id:",
    )
    kept = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(n in s for n in noise):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def build_public_directive() -> str:
    return (
        "You are writing a short WhatsApp reply for Dario to an external contact.\n"
        "PUBLIC REPLY MODE.\n"
        "Rules:\n"
        "1. Keep it concise and human.\n"
        "2. Do not mention Codex, bots, triggers, automation, policy, or internals.\n"
        "3. Do not claim real-world actions you did not observe.\n"
        "4. If uncertain, say Dario will reply soon.\n"
        "5. Reply in the same language as the incoming message.\n"
        "6. Return only final reply text.\n\n"
        "Message:\n"
    )


def build_trusted_directive() -> str:
    return (
        "You are Kuun, Dario's trusted WhatsApp agent.\n"
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


def ask_codex(query: str, mode: str = "public_reply"):
    codex_bin = "/opt/homebrew/bin/codex"
    if not os.path.exists(codex_bin):
        codex_bin = "codex"

    directive = build_public_directive() if mode == "public_reply" else build_trusted_directive()
    prompt = directive + query
    cmd = [codex_bin, "exec", "--skip-git-repo-check", "-C", os.path.expanduser("~"), prompt]

    try:
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = clean_output((res.stdout or "") + (res.stderr or ""))
        if not out:
            out = "Dario will reply soon."
        print(out)
    except subprocess.TimeoutExpired:
        print("Dario will reply soon.")
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query Codex for safe WhatsApp replies.")
    parser.add_argument("query", nargs="+", help="Message text")
    parser.add_argument("--mode", choices=["public_reply", "trusted_reply"], default="public_reply")
    args = parser.parse_args()
    ask_codex(" ".join(args.query), mode=args.mode)
