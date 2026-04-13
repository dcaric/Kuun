# Kuun

Kuun is a minimal WhatsApp bridge for Gemini CLI.

It is a lightweight fork/spinoff of Satele, focused only on the Gemini-bridge flow:
- Satele repo: https://github.com/dcaric/Satele

Main flow:
1. You send: `<bot-name> - <question>` or `<bot-name> g <question>`
2. Kuun starts Gemini CLI in the background
3. Kuun sends final output back to your WhatsApp

## Major Strengths

- **Practical Orchestrator**: Kuun is a lightweight orchestrator that enables simple, reliable communication between WhatsApp and Gemini CLI.
- **Run Anywhere You Own**: Works on your home machine or on a cloud VPS, so you can keep the same WhatsApp workflow in both setups.
- **Asynchronous by Design**: Long Gemini tasks run in the background and return results when complete, without blocking interaction.
- **Autonomous Heartbeat + Scheduler**: Kuun can run periodic tasks and proactively inform you via WhatsApp, giving it real agent-like behavior.
- **Easy to Extend**: Today it is optimized for Gemini CLI, but the architecture can be extended to other CLI agents like Codex and Claude Code.
- **Operationally Simple**: Small codebase, focused scope, explicit ports, and CLI controls (`start/stop/restart/status`) make it easy to maintain.

## Platform Support

- **macOS**: ✅ Fully supported in current setup
- **Linux**: ✅ Mostly supported (same architecture, but not fully documented yet)
- **Docker**: ⚠️ Not production-ready yet (no official Dockerfile/compose in Kuun repo at the moment)

Note:
- Kuun currently uses a pseudo-terminal wrapper for stable Gemini background execution.
- If needed, Linux-specific tuning for that wrapper can be added quickly.

## Linux Setup

Install prerequisites (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install -y python3 python3-venv nodejs npm util-linux
```

Why `util-linux`:
- Kuun uses the `script` command for stable Gemini background execution.

Then setup Kuun:

```bash
cd /path/to/Kuun
./kuun setup
./kuun start
./kuun status
```

## Linux systemd (Optional)

Example unit file `/etc/systemd/system/kuun.service`:

```ini
[Unit]
Description=Kuun WhatsApp Gemini Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=YOUR_USER
WorkingDirectory=/path/to/Kuun
ExecStart=/path/to/Kuun/kuun start
ExecStop=/path/to/Kuun/kuun stop
RemainAfterExit=yes
TimeoutStartSec=120
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

Enable/start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable kuun
sudo systemctl start kuun
sudo systemctl status kuun
```

## Ports (No Clash With Satele)

Kuun defaults:
- FastAPI: `8100`
- WhatsApp Send API: `8101`

Satele typically uses `8000`/`8001`, so they can run in parallel.

## Installation

```bash
git clone <your-kuun-repo-url> ~/Kuun
cd ~/Kuun
./kuun setup
```

## Gemini CLI Setup (Required)

Kuun sends your WhatsApp prompts to the local `gemini` CLI binary.
So Gemini CLI must be installed and authenticated on the same machine where Kuun runs.

### 1) Install Gemini CLI

macOS (Homebrew):

```bash
brew install gemini-cli
```

Linux (npm global):

```bash
sudo npm install -g @google/gemini-cli
```

Verify:

```bash
which gemini
gemini --version
```

### 2) Authenticate Gemini CLI

Option A (OAuth login):

```bash
gemini auth login
```

Option B (API key):
- Put your key in `kuun.config` via:

```bash
kuun geminikey YOUR_API_KEY
```

Kuun can work with either OAuth or API key.  
If OAuth session expires, is revoked, or stops working, just run `gemini auth login` again.

### 3) Quick Gemini CLI test before Kuun

```bash
gemini -y -p "Say hello from Gemini CLI"
```

If this command fails, Kuun background Gemini jobs will also fail.

### 4) Typical auth/API troubleshooting

- Check if OAuth is still valid:

```bash
gemini models list
```

- Re-login OAuth:

```bash
gemini auth login
```

- If using API key, confirm key exists in config:

```bash
rg '^GOOGLE_API_KEY=' kuun.config
```

## First-Time Config

```bash
cp kuun.config.example kuun.config
./kuun name m1
./kuun geminikey YOUR_API_KEY
```

Set a strong bridge secret in `kuun.config` before starting:

```bash
BRIDGE_SECRET_KEY=<your-random-secret>
```

Example generator:

```bash
openssl rand -hex 32
```

Add your WhatsApp number to allowlist:

```bash
kuun add-number 38591...
kuun users
```

Without allowed numbers, Kuun denies trigger execution by default.

## Start / Stop

```bash
./kuun start
./kuun status
./kuun stop
./kuun restart
```

## Use `kuun` Instead of `./kuun`

By default, shell runs `./kuun` because the project folder is not in `PATH`.
Add Kuun to PATH once, then you can use plain `kuun` command.

On macOS (zsh):

```bash
echo 'export PATH="/Users/dcaric/Working/ml/Kuun:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

After that:

```bash
kuun start
kuun status
kuun restart
```

## WhatsApp Linking

```bash
kuun whatsapp link
```

Scan QR code in terminal (Linked Devices in WhatsApp).

## WhatsApp Usage

Examples:
- `m1 - what is the capital of Croatia?`
- `m1 g summarize this text: ...`

## Scheduler (WhatsApp)

- `m1 set job which will at 13h check weather in Split`
- `m1 list all scheduled jobs`
- `m1 remove the scheduled job with ID abc12345`

Notes:
- Scheduled jobs are stored in `brain/scheduled_jobs.json`
- Jobs run daily at configured time and send results back to the same WhatsApp sender

## Whitelist Numbers

- `kuun add-number <num>`
- `kuun remove-number <num>`
- `kuun users`

Notes:
- Numbers are stored in `allowed_numbers.txt`
- If allowlist is empty, Kuun denies all trigger execution
- If allowlist has entries, only those numbers can trigger Kuun

## Commands

- `kuun setup`
- `kuun start`
- `kuun stop`
- `kuun restart`
- `kuun status`
- `kuun name <name>`
- `kuun geminikey <key>`
- `kuun add-number <num>`
- `kuun remove-number <num>`
- `kuun users`
- `kuun whatsapp link`

## Config Keys (`kuun.config`)

- `BOT_TRIGGER`
- `GOOGLE_API_KEY`
- `BRIDGE_SECRET_KEY` (required, must not be default)
- `FASTAPI_PORT`
- `WA_API_PORT`
- `SERVER_BIND_HOST` (default `127.0.0.1`)
- `WA_API_BIND_HOST` (default `127.0.0.1`)
- `REMOTE_BRIDGE_URL`
- `POLL_INTERVAL`
- `HEARTBEAT_INTERVAL`
- `SYSTEM_AWAKE`
