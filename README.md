# Kuun

Kuun is a WhatsApp bridge for Gemini CLI with safe conversational auto-replies.

It is a lightweight fork/spinoff of Satele, focused on the Gemini bridge flow:
- Satele repo: https://github.com/dcaric/Satele

Main flow:
1. You send: `<bot-name> - <question>` or `<bot-name> g <question>`
2. Kuun starts Gemini CLI in the background
3. Kuun sends final output back to your WhatsApp

Conversational flow (new):
1. Kuun now routes all incoming text messages (not only trigger commands)
2. It chooses one mode:
   - `agent`: trusted sender + trigger present
   - `trusted_chat`: trusted sender + no trigger
   - `public_chat`: non-trusted sender + no trigger
3. In `trusted_chat` and `public_chat`, Kuun sends safe conversational replies and does not run Gemini jobs

## Major Strengths

- **Practical orchestrator**: Simple, reliable communication between WhatsApp and Gemini CLI.
- **Run anywhere you own**: Home machine or cloud VPS.
- **Asynchronous by design**: Long Gemini tasks run in background.
- **Autonomous heartbeat + scheduler**: Periodic tasks with proactive WhatsApp updates.
- **Easy to extend**: Can be adapted for Codex CLI / Claude Code in future.
- **Operationally simple**: Focused scope and clear CLI controls.
- **Safer conversational mode**: Non-trigger chats reply without full agent execution.

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
- Triggered commands should start with that exact name at the beginning (example: `kuun - who are you`).
- Normal messages are now still routed for conversational replies, but only trigger+trusted path enters full agent mode.

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
- Kuun uses deny-by-default allowlist for trusted/agent path.
- If no numbers are allowed, no external sender can enter `agent` mode.
- Non-trigger messages can still receive conversational replies (`public_chat`).

### 6b) Optional trusted names

You can also trust contacts by WhatsApp display name:

```env
TRUSTED_NAMES=Dario,Dario Caric
```

If a sender name matches this list, trigger commands from that contact can enter `agent` mode.

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
- `hello` (public/trusted conversational reply mode)

## WhatsApp Reply Routing (New)

Kuun now replies to ordinary WhatsApp text messages, not only explicit trigger commands.

Mode rules:
- `agent`: sender is trusted and message contains trigger word (`BOT_TRIGGER`)
- `trusted_chat`: sender is trusted but message has no trigger
- `public_chat`: sender is not trusted and message has no trigger

Security behavior:
- `agent` mode can run Gemini background tasks and system commands.
- `trusted_chat` and `public_chat` do **not** run Gemini background jobs.
- Conversational replies in those safe modes are generated through a restricted path (`brain/ask_codex.py`) without dangerous execution flags.
- Outbound self-loop prevention remains enabled (`fromMe` autonomous conversation is blocked unless explicitly triggered).
- Human intervention cooldown: after your manual outgoing WhatsApp message, Kuun stays silent in `trusted_chat` for `HUMAN_INTERVENTION_TIMEOUT` seconds (default `300`).

Ack behavior:
- `🤖 [<trigger>] Working...` is sent only for `agent` mode (trusted trigger).

## Allowed List For Conversational Replies

Kuun now answers conversational messages only for contacts in the whitelist.

WhatsApp commands:
- `<bot-name> whitelist add <name-or-partial>`
- `<bot-name> whitelist remove <name-or-partial>`
- `<bot-name> whitelist`
- `<bot-name> whitelist group add <group-id-or-name>`
- `<bot-name> whitelist group remove <group-id-or-name>`
- `<bot-name> whitelist group`

How matching works:
- Entries are stored in `whitelist.json`.
- Matching is case-insensitive against both contact `pushName` and sender JID.
- If matched, Kuun replies in `trusted_chat` and `public_chat`.
- If not matched, Kuun does not reply in conversational modes.
- Triggered `agent` tasks are not blocked by this conversational whitelist.
- For group chats, Kuun replies only when:
  - the message is a direct reply to Kuun, or
  - the group is whitelisted by ID or group name.
- Group entries are stored in `whitelist_groups.json`; discovered group names are cached in `group_cache.json`.

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
echo 'export PATH="$HOME/Kuun:$PATH"' >> ~/.zshrc
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
- `TRUSTED_NAMES`
