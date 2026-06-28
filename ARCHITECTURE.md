# Kuun Architecture

This document describes the technical architecture of Kuun, a lightweight WhatsApp-controlled AI agent for a home machine.

## Table of Contents

- [Overview](#overview)
- [System Components](#system-components)
- [Data Flow](#data-flow)
- [Command Modes](#command-modes)
- [Background Jobs](#background-jobs)
- [Scheduler And Heartbeat](#scheduler-and-heartbeat)
- [Configuration](#configuration)
- [Security Model](#security-model)
- [Runtime Files](#runtime-files)
- [Operational Commands](#operational-commands)

---

## Overview

Kuun is a small multi-process system that connects WhatsApp messages to local AI helper processes. It is designed around a simple queue:

1. WhatsApp receives a message.
2. The Node.js bridge forwards the message to the local FastAPI server.
3. The Python monitor polls the server for tasks.
4. The monitor starts Gemini or Codex jobs in the background.
5. Results are posted back through FastAPI to the WhatsApp bridge.
6. The bridge sends the final message back to WhatsApp.

```text
┌──────────────────┐
│ WhatsApp User    │
└────────┬─────────┘
         │ message / command
         ▼
┌──────────────────────────┐
│ whatsapp_bridge.mjs      │
│ Node.js + Baileys        │
│ WA send API: 8101        │
└────────┬─────────────────┘
         │ POST /webhook/message
         ▼
┌──────────────────────────┐
│ server/main.py           │
│ FastAPI queue server     │
│ API: 8100                │
└────────┬─────────────────┘
         │ GET /get-task
         ▼
┌──────────────────────────┐
│ brain/monitor.py         │
│ Task router / supervisor │
└─────┬──────────────┬─────┘
      │              │
      ▼              ▼
┌──────────────┐  ┌──────────────┐
│ Gemini API   │  │ Codex CLI    │
│ ask_gemini   │  │ ask_codex    │
└──────┬───────┘  └──────┬───────┘
       │ result file      │ result file
       └──────────┬───────┘
                  ▼
          POST /report-result
                  ▼
          WhatsApp reply
```

---

## System Components

### 1. CLI Controller (`kuun`)

**Purpose:** Starts, stops, configures, and inspects the Kuun runtime.

**Responsibilities:**

- Creates `kuun.config` from `kuun.config.example` if missing.
- Backfills required config keys such as `GEMINI_MODEL`, `AI_PROVIDER`, `CODEX_MODEL`, and token price metadata.
- Runs dependency setup through `requirements.txt` and `package.json`.
- Starts four background processes:
  - `server/main.py`
  - `whatsapp_bridge.mjs`
  - `brain/monitor.py`
  - `brain/heartbeat.py`
- Provides admin commands like `add-number`, `geminikey`, `gemini`, `tokens`, `awake`, and `whatsapp link`.

### 2. WhatsApp Bridge (`whatsapp_bridge.mjs`)

**Purpose:** Maintains the WhatsApp Web connection and exposes a local send endpoint.

**Technology:**

- Node.js
- Baileys (`@whiskeysockets/baileys`)
- Express for local send API
- `qrcode-terminal` for pairing QR codes

**Key Behavior:**

- Authenticates WhatsApp through `.kuun_cache`.
- `kuun whatsapp link` resets `.kuun_cache` and forces a fresh QR code.
- Receives WhatsApp messages through Baileys `messages.upsert` events.
- Detects trigger commands using `BOT_TRIGGER`.
- Differentiates admin commands, trusted chat, public chat, groups, and bot-like echoes.
- Maps WhatsApp LID identifiers back to phone numbers using `.kuun_cache/lid-mapping-*` files.
- Allows owner/self commands with `ALLOW_FROMME_SYSTEM=true`.
- Sends replies via local `POST /send` on `WA_API_PORT`.

**Local Endpoint:**

```text
POST http://127.0.0.1:8101/send
Authorization: Bearer <BRIDGE_SECRET_KEY>
Body: { "to": "<jid-or-phone>", "text": "<message>" }
```

### 3. FastAPI Queue Server (`server/main.py`)

**Purpose:** Provides a small authenticated queue between the WhatsApp bridge and monitor.

**Technology:**

- Python
- FastAPI
- Uvicorn

**Endpoints:**

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/` | `GET` | Health/status check. |
| `/webhook/message` | `POST` | Receives inbound WhatsApp tasks from the bridge. |
| `/get-task` | `GET` | Polled by `monitor.py` to fetch the next queued task. |
| `/status-update` | `POST` | Sends intermediate status messages back to WhatsApp. |
| `/report-result` | `POST` | Sends final task output back to WhatsApp. |

**Queue Model:**

- Tasks are held in memory in `tasks_queue`.
- Result metadata is held in memory in `results`.
- This is intentionally simple; queued tasks do not survive a server restart.

### 4. Monitor (`brain/monitor.py`)

**Purpose:** Polls the queue server, routes commands, and supervises background Gemini/Codex jobs.

**Main Responsibilities:**

- Polls `REMOTE_BRIDGE_URL/get-task` every `POLL_INTERVAL` seconds.
- Verifies admin permissions through `ALLOWED_NUMBERS` and `fromMe` metadata.
- Routes recognized commands:
  - Gemini shortcuts: `- <query>`, `g <query>`, `ask geminicli - <query>`
  - Codex shortcuts: `c <task>`, `codex <task>`, `ask codex - <task>`
  - Scheduler commands
  - Whitelist/contact commands
  - Status/help/restart commands
- Spawns long-running Gemini and Codex tasks as child processes.
- Tracks active jobs in memory:
  - `ACTIVE_GEMINI_JOBS`
  - `ACTIVE_CODEX_JOBS`
- Reads result files from `media/` and posts final output back to the queue server.

### 5. Gemini Runner (`brain/ask_gemini_cli.py`)

**Purpose:** Runs Gemini tasks and writes results for the monitor.

**Primary Mode:**

- Uses `google-genai` with `GOOGLE_API_KEY`.
- Default model is `GEMINI_MODEL=gemini-3.1-flash-lite`.

**Fallback Mode:**

- If API execution fails and provider is not explicitly CLI-only, it falls back to Gemini CLI.
- Gemini CLI is run with non-interactive flags and a pseudo-terminal wrapper when available.

**Inputs/Outputs:**

```bash
python3 brain/ask_gemini_cli.py "question" --output media/gemini_<task_id>.txt
```

The script prints the cleaned result to stdout and writes it to the output file if provided.

### 6. Codex Runner (`brain/ask_codex.py`)

**Purpose:** Runs Codex tasks for either safe WhatsApp replies or private background agent jobs.

**Modes:**

| Mode | Purpose |
| --- | --- |
| `public_reply` | Short safe replies for external/untrusted contacts. |
| `trusted_reply` | Warm concise replies for trusted contacts. |
| `private_agent` | Background Codex task execution in the Kuun repo. |

**CLI Selection:**

Kuun prefers the bundled Codex Desktop CLI:

```text
/Applications/Codex.app/Contents/Resources/codex
```

It falls back to `/opt/homebrew/bin/codex` or `codex` from `PATH`.

**Model:**

- Configured by `CODEX_MODEL`.
- Default: `gpt-5.4`.

**Inputs/Outputs:**

```bash
python3 brain/ask_codex.py "task" --mode private_agent --output media/codex_<task_id>.txt
```

---

## Data Flow

### Triggered Gemini Command

Example WhatsApp message:

```text
kuun - what time is it in Zagreb?
```

Flow:

1. `whatsapp_bridge.mjs` receives the message.
2. It verifies the sender is an admin number or allowed `fromMe` user.
3. It forwards the message to `POST /webhook/message`.
4. `server/main.py` strips the trigger and queues the task.
5. `brain/monitor.py` polls `/get-task` and sees the `- <query>` shortcut.
6. Monitor sends a status update: “Gemini job started in background.”
7. Monitor starts `brain/ask_gemini_cli.py` as a subprocess.
8. Gemini output is written to `media/gemini_<task_id>.txt`.
9. Monitor reads the file and posts `/report-result`.
10. Server calls `POST /send` on the WhatsApp bridge.
11. Bridge sends the final answer to WhatsApp.

### Triggered Codex Command

Example WhatsApp message:

```text
kuun c check whether README and CLI help are consistent
```

Flow is the same as Gemini, except monitor starts `brain/ask_codex.py` in `private_agent` mode and writes output to `media/codex_<task_id>.txt`.

### Conversational Reply

For trusted contacts or allowlisted groups, Kuun can produce a short reply without full agent execution:

1. Bridge marks the task as `trusted_chat` or `public_chat`.
2. Monitor calls `safe_conversational_reply()`.
3. `brain/ask_codex.py` runs in `trusted_reply` or `public_reply` mode.
4. The result is sent back through the normal `/report-result` path.

---

## Command Modes

| Mode | Set By | Purpose |
| --- | --- | --- |
| `agent` | Triggered admin command | Allows Gemini/Codex background jobs, scheduler, status, restart, and whitelist management. |
| `trusted_chat` | Trusted sender without trigger | Short safe conversational replies. |
| `public_chat` | Non-admin/non-trusted conversational path | Restricted public-style fallback replies. |

Kuun does not expose a remote raw shell command mode.

---

## Background Jobs

### Gemini Jobs

Recognized forms after trigger stripping:

```text
- <query>
g <query>
ask geminicli - <query>
```

Active Gemini jobs are tracked in `ACTIVE_GEMINI_JOBS`. Output files are stored in `media/`.

### Codex Jobs

Recognized forms after trigger stripping:

```text
c <task>
codex <task>
ask codex - <task>
```

Active Codex jobs are tracked in `ACTIVE_CODEX_JOBS`. Output files are stored in `media/`.

---

## Scheduler And Heartbeat

### Scheduler Commands

Kuun supports recurring daily jobs defined through WhatsApp:

```text
kuun set job which will at 13h check weather in Split
kuun list jobs
kuun remove job <id>
```

Jobs are stored in:

```text
brain/scheduled_jobs.json
```

### Heartbeat (`brain/heartbeat.py`)

**Purpose:** Keeps a lightweight periodic process alive and checks scheduled jobs.

**Behavior:**

- Sleeps for `HEARTBEAT_INTERVAL` seconds.
- Loads `brain/scheduled_jobs.json`.
- Runs due jobs once per day.
- Executes scheduled queries through `brain/ask_gemini_cli.py`.
- Sends scheduled results through the WhatsApp send API.

---

## Configuration

Kuun is configured by `kuun.config`, created from `kuun.config.example`.

| Key | Purpose |
| --- | --- |
| `BOT_TRIGGER` | WhatsApp trigger word, default `kuun`. |
| `BRIDGE_SECRET_KEY` | Bearer token shared by server, bridge, monitor, and heartbeat. |
| `ALLOWED_NUMBERS` | Comma-separated admin phone numbers. |
| `FASTAPI_PORT` | Queue server port, default `8100`. |
| `WA_API_PORT` | WhatsApp send API port, default `8101`. |
| `SERVER_BIND_HOST` | FastAPI bind host, default `127.0.0.1`. |
| `WA_API_BIND_HOST` | WhatsApp send API bind host, default `127.0.0.1`. |
| `REMOTE_BRIDGE_URL` | Monitor polling URL for FastAPI. |
| `POLL_INTERVAL` | Monitor polling interval in seconds. |
| `HEARTBEAT_INTERVAL` | Heartbeat interval in seconds. |
| `GOOGLE_API_KEY` | Gemini API key. |
| `GEMINI_MODEL` | Gemini model, default `gemini-3.1-flash-lite`. |
| `AI_PROVIDER` | AI provider selector, default `gemini`. |
| `CODEX_MODEL` | Codex model, default `gpt-5.4`. |
| `GEMINI_PRICE_IN` | Gemini input price metadata. |
| `GEMINI_PRICE_OUT` | Gemini output price metadata. |
| `GMAIL_APP_PASSWORD` | Optional Gmail app password stored for future integrations. |
| `SYSTEM_AWAKE` | Whether `kuun start` should keep the machine awake. |
| `HUMAN_INTERVENTION_TIMEOUT` | Cooldown after manual human replies. |
| `ALLOW_FROMME_SYSTEM` | Allows the linked owner account to trigger admin commands. |

---

## Security Model

Kuun is designed to be local-first and deny-by-default.

### Local API Auth

All internal write/task endpoints require:

```text
Authorization: Bearer <BRIDGE_SECRET_KEY>
```

This protects:

- `POST /webhook/message`
- `GET /get-task`
- `POST /status-update`
- `POST /report-result`
- `POST /send`

### Admin Authorization

Agent commands require one of:

- Sender phone is present in `ALLOWED_NUMBERS`.
- Message is from the linked owner account and `ALLOW_FROMME_SYSTEM=true`.

### WhatsApp LID Mapping

Modern WhatsApp can expose sender IDs as LIDs rather than phone numbers. Kuun resolves these through `.kuun_cache/lid-mapping-*` files so admin allowlists still work.

### Group Safety

Groups are ignored unless:

- The message directly replies to the bot, or
- The group is explicitly allowlisted through `whitelist group add`.

### No Remote Shell Shortcut

Kuun intentionally does not expose a raw remote shell command such as:

```text
run command - <cmd>
```

Codex background jobs can reason about code and tasks, but they are routed through Codex CLI and the configured Codex safety model rather than a direct shell executor.

---

## Runtime Files

| Path | Purpose |
| --- | --- |
| `.kuun_cache/` | WhatsApp auth/session files. Ignored by git. |
| `.kuun_cache.backup.*` | Backups created by `kuun whatsapp link` before forcing a fresh QR. |
| `kuun.config` | Local secrets/configuration. Should not be committed. |
| `kuun.log` | Combined service log. |
| `media/` | Background job output files. |
| `whitelist.json` | Trusted contact allowlist. |
| `whitelist_groups.json` | Trusted group allowlist. |
| `contacts_cache.json` | WhatsApp contact-name cache. |
| `group_cache.json` | WhatsApp group-name cache. |
| `brain/scheduled_jobs.json` | Scheduler job definitions. |

---

## Operational Commands

### Service Management

```bash
kuun setup
kuun start
kuun stop
kuun restart
kuun status
kuun kill
```

### Configuration

```bash
kuun name kuun
kuun geminikey <key>
kuun gemini gemini-3.1-flash-lite
kuun tokens 0.10 0.40
kuun add-number 385911234567
kuun users
```

### WhatsApp Linking

```bash
kuun whatsapp link
```

This resets `.kuun_cache`, backs it up, and shows a fresh QR code.

### Logs

```bash
tail -f kuun.log
```
