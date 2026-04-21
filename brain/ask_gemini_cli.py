#!/usr/bin/env python3
import argparse
import datetime
import os
import re
import shutil
import subprocess


def clean_output(text: str) -> str:
    # Remove ANSI escape sequences and carriage returns.
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    text = text.replace("\r", "")

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
    ]
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if any(n in s for n in noise):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def run_gemini(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")

    # Gemini CLI can fail in detached mode with setRawMode EIO.
    # Running through `script` provides a pseudo-terminal.
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


def ask_gemini_cli(query: str, output_file: str | None = None):
    now = datetime.datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
    full_query = f"[Context: Today is {now}] {query}"

    gemini_bin = "/opt/homebrew/bin/gemini"
    if not os.path.exists(gemini_bin):
        gemini_bin = "gemini"

    cmd = [gemini_bin, "-y", "-p", full_query]

    try:
        res = run_gemini(cmd, timeout=600)
        output = (res.stdout or "") + (res.stderr or "")
        cleaned = clean_output(output)

        if "setRawMode EIO" in cleaned:
            cleaned = "Gemini CLI failed in detached terminal mode (setRawMode EIO). Please retry once; if it repeats, run `kuun whatsapp link` in foreground and test again."

        if not cleaned:
            cleaned = "No output received from Gemini CLI."

        # If explicit answer tags are present, return only inside them.
        m = re.search(r"<answer>(.*?)</answer>", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()

    except subprocess.TimeoutExpired:
        cleaned = "Gemini CLI timed out after 10 minutes."
    except Exception as exc:
        cleaned = f"Gemini CLI execution error: {exc}"

    print(cleaned)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(cleaned)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gemini CLI query")
    parser.add_argument("query", nargs="+", help="Gemini query")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    ask_gemini_cli(" ".join(args.query), output_file=args.output)
