# Kuun

Kuun is a minimal WhatsApp bridge for Gemini CLI.

It is a lightweight fork/spinoff of Satele, focused on the Gemini bridge flow:
- Satele repo: https://github.com/dcaric/Satele

Main flow:
1. You send: `<bot-name> - <question>` or `<bot-name> g <question>`
2. Kuun starts Gemini CLI in the background
3. Kuun sends final output back to your WhatsApp

## Major Strengths

- **Practical orchestrator**: Simple, reliable communication between WhatsApp and Gemini CLI.
- **Run anywhere you own**: Home machine or cloud VPS.
- **Asynchronous by design**: Long Gemini tasks run in background.
- **Autonomous heartbeat + scheduler**: Periodic tasks with proactive WhatsApp updates.
- **Easy to extend**: Can be adapted for Codex CLI / Claude Code in future.
- **Operationally simple**: Focused scope and clear CLI controls.

## End-to-End Setup (All In One Place)

### 1) Install system prerequisites

macOS:

```bash
brew install node python@3.11 gemini-cli
```

Linux (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install -y python3 python3-venv nodejs npm util-linux
sudo npm install -g @google/gemini-cli
```

### 2) Clone and install Kuun dependencies

```bash
git clone https://github.com/dcaric/Kuun.git ~/Kuun
cd ~/Kuun
./kuun setup
```

### 3) Create and edit `kuun.config`

```bash
cp kuun.config.example kuun.config
```

Required values in `kuun.config`:

```env
BOT_TRIGGER=m1
BRIDGE_SECRET_KEY=<strong_random_secret>
GOOGLE_API_KEY=<optional_if_you_use_api_key_mode>
FASTAPI_PORT=8100
WA_API_PORT=8101
SERVER_BIND_HOST=127.0.0.1
WA_API_BIND_HOST=127.0.0.1
REMOTE_BRIDGE_URL=http://localhost:8100
POLL_INTERVAL=2
HEARTBEAT_INTERVAL=30
```

Generate a secure bridge secret:

```bash
openssl rand -hex 32
```

### 4) Configure bot name and optional Gemini API key

```bash
kuun name <insert name>
kuun geminikey YOUR_API_KEY   # optional if you use OAuth login
```

Important:
- Replace `<insert name>` with your real trigger name (for example: `m1` or `kuun`).
- In WhatsApp, commands must start with that exact name at the beginning of the message (example: `kuun - who are you`).
- This is how Kuun knows the message is for it; normal chats from others will not trigger Kuun.

### 5) Authenticate Gemini CLI (required)

OAuth login:

```bash
gemini auth login
```

Verify Gemini CLI is usable:

```bash
gemini --version
gemini -y -p "Say hello from Gemini CLI"
```

If OAuth expires later, run `gemini auth login` again.

### 6) Add allowed WhatsApp number(s)

```bash
kuun add-number 38591...
kuun users
```

Important:
- Kuun uses deny-by-default allowlist behavior.
- If no numbers are allowed, trigger execution is blocked.

### 7) Start Kuun services

```bash
kuun start
kuun status
```

Expected running services:
- FastAPI
- WhatsApp Bridge
- AI Monitor
- Heartbeat

### 8) Link WhatsApp (QR)

```bash
kuun whatsapp link
```

Scan QR in WhatsApp -> Linked Devices.

### 9) First WhatsApp test

Send from WhatsApp:
- `kuun help`
- `kuun - what time is it in Zagreb?`

## Daily Usage

```bash
kuun start
kuun stop
kuun restart
kuun status
```

WhatsApp examples:
- `kuun - summarize latest AI trends`
- `kuun g explain docker volumes simply`
- `kuun status`
- `kuun help`

## Scheduler (WhatsApp)

- `kuun set job which will at 13h check weather in Split`
- `kuun list jobs`
- `kuun remove the scheduled job with ID abc12345`

Notes:
- Scheduled jobs are stored in `brain/scheduled_jobs.json`.
- Jobs run daily at configured time and send results to the same sender.

## Whitelist Commands

- `kuun add-number <num>`
- `kuun remove-number <num>`
- `kuun users`

## Make `kuun` global command (optional)

macOS (zsh):

```bash
echo 'export PATH="/Users/dcaric/Working/ml/Kuun:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## Platform Notes

- **macOS**: supported
- **Linux**: supported (with prerequisites above)
- **Docker**: not production-ready yet in this repo

## Security Notes

- `BRIDGE_SECRET_KEY` is required and must not be default.
- Internal APIs are authenticated.
- Services bind to localhost by default.
- Runtime/session files are ignored via `.gitignore`.

## Config Keys (`kuun.config`)

- `BOT_TRIGGER`
- `BRIDGE_SECRET_KEY`
- `GOOGLE_API_KEY`
- `FASTAPI_PORT`
- `WA_API_PORT`
- `SERVER_BIND_HOST`
- `WA_API_BIND_HOST`
- `REMOTE_BRIDGE_URL`
- `POLL_INTERVAL`
- `HEARTBEAT_INTERVAL`
- `SYSTEM_AWAKE`
