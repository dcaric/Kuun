#!/usr/bin/env python3
import argparse
import datetime
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "kuun.config")


def load_kuun_context() -> str:
    context_path = PROJECT_ROOT / "KUUN.md"
    if not context_path.exists():
        return ""
    try:
        return context_path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def clean_output(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text or "").replace("\r", "")
    # Strip End-of-Transmission (EOT) control characters and literal '^D' terminal artifacts
    text = text.replace("\x04", "").replace("^D", "")

    answer_match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    if answer_match:
        return answer_match.group(1).strip()

    noise = [
        "DeprecationWarning",
        "node --trace-deprecation",
        "YOLO mode is enabled",
        "All tool calls will be automatically approved",
        "Loaded cached credentials",
        "Registering notification handlers for server",
        "Scheduling MCP context refresh",
        "Executing MCP context refresh",
        "MCP context refresh complete",
        "Logged in with Google:",
    ]
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(item in stripped for item in noise):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def build_prompt(query: str) -> str:
    now = datetime.datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
    kuun_context = load_kuun_context()
    context_block = f"\n\n### KUUN CONTEXT\n{kuun_context}\n" if kuun_context else ""
    
    # Retrieve memory context
    memory_context = ""
    try:
        from brain.memory import Memory
        mem = Memory(silent=True)
        recent = mem.recall_recent(n_results=15)
        matches = mem.recall(query, n_results=5)
        
        blocks = []
        if matches:
            blocks.append("### RELEVANT PAST INTERACTIONS (MEMORIES)\nHere are matching interactions from your past history that are relevant to the user query:\n" + "\n".join(matches))
        if recent:
            blocks.append("### RECENT CHAT & SYSTEM MEMORY\nHere is a log of your most recent interactions:\n" + "\n".join(recent))
        
        if blocks:
            memory_context = "\n\n" + "\n\n".join(blocks)
    except Exception:
        pass

    return (
        f"[Context: Today is {now}]\n"
        "Return a direct, useful answer. If this is for WhatsApp, keep it concise unless detail is requested.\n"
        "IMPORTANT: You have direct access to run shell commands and check real-time system metrics (like disk usage, CPU, processes, memory, or local files) via your tool calling capabilities. "
        "Use these tools directly to check the actual state of the system or run commands when requested. "
        "Never guess or hallucinate local system values; always execute the appropriate tool/command to get the ground truth.\n\n"
        f"{context_block}"
        f"{memory_context}"
        "\n\n### USER REQUEST\n"
        f"{query}"
    )


def ask_gemini_api(query: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key or api_key.lower().startswith("your_"):
        raise RuntimeError("GOOGLE_API_KEY is not configured")

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed. Run `kuun setup` first.") from exc

    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=build_prompt(query))
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini API returned an empty response")
    return clean_output(text)


def run_gemini_cli(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")

    script_bin = shutil.which("script")
    if script_bin:
        wrapped_cmd = [script_bin, "-q", "/dev/null", *cmd]
    else:
        wrapped_cmd = cmd

    return subprocess.run(
        wrapped_cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def ask_gemini_cli_fallback(query: str) -> str:
    agy_bin = "/opt/homebrew/bin/agy"
    if not os.path.exists(agy_bin):
        agy_bin = "agy"

    cmd = [agy_bin, "--dangerously-skip-permissions", "-p", build_prompt(query)]
    res = run_gemini_cli(cmd, timeout=600)
    cleaned = clean_output((res.stdout or "") + (res.stderr or ""))
    if "setRawMode EIO" in cleaned:
        return "Agy CLI failed in detached terminal mode (setRawMode EIO). Configure GOOGLE_API_KEY with `kuun geminikey <key>` and run `kuun setup`."
    return cleaned or "No output received from Agy CLI."


def ask_gemini(query: str, output_file: str | None = None, provider: str | None = None):
    # Always execute via agy CLI so the agent has tool access to local commands
    try:
        result = ask_gemini_cli_fallback(query)
    except Exception as exc:
        result = f"Agy CLI execution failed: {exc}"

    result = clean_output(result) or "Agy CLI returned an empty response."
    print(result)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as handle:
            handle.write(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gemini through API key, with Gemini CLI fallback")
    parser.add_argument("query", nargs="+", help="Gemini query")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--provider", choices=["gemini", "api", "gemini_api", "cli", "gemini_cli"], help="Override AI provider")
    args = parser.parse_args()
    ask_gemini(" ".join(args.query), output_file=args.output, provider=args.provider)
