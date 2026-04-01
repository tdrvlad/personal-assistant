# Pi Assistant

A voice-activated personal assistant that runs on a Raspberry Pi 5. It listens for a custom wake word, understands speech in English and Romanian, thinks with Claude, and talks back — all while managing your notes, todos, calendar, and reminders. When you're away from home, the same assistant is available via a Telegram bot on your phone.

## What it does

**At home (voice):** Say your wake word, and the assistant listens. Ask it to add something to your grocery list, check your calendar, create a reminder, or just have a conversation. It responds out loud through a speaker. After responding, it stays listening for 30 seconds so you can have a natural back-and-forth without repeating the wake word.

**On the go (Telegram):** Text the same assistant from your phone. Ask for your grocery list from the supermarket, dictate a quick idea, or check what's on your calendar tomorrow. Same tools, same memory, same knowledge — just text instead of voice.

**Proactively:** The assistant can wake up on its own. Set a reminder for 6pm, and at 6pm it plays a chime and tells you. Set a daily morning briefing, and every day at 9am it reads your calendar and todos. Proactive messages are spoken aloud at home and pushed to Telegram so you get them wherever you are.

**It remembers you:** The assistant learns facts about you over time — your preferences, your ongoing projects, people you mention, decisions you make. This knowledge is stored locally and retrieved automatically so the assistant always has the right context without you having to repeat yourself.

## How it works

The system is split into small services, each doing one thing. Audio services run directly on the Pi for hardware access. Everything else runs in Docker containers.

```
┌─────────────────────────────────────────────────────────────┐
│  Raspberry Pi 5                                             │
│                                                             │
│  Host: openWakeWord → faster-whisper (STT) → piper (TTS)   │
│                                                             │
│  Docker:                                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Orchestrator                                       │    │
│  │  Session management, memory retrieval,              │    │
│  │  context assembly                                   │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                   │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │  Claude Agent (claude-agent-sdk)                    │    │
│  │  Tools: remember, forget, filesystem, web search    │    │
│  └──┬────────┬────────┬────────┬───────────────────────┘    │
│     │        │        │        │                            │
│  ┌──▼──┐ ┌──▼──┐ ┌───▼──┐ ┌──▼──────┐ ┌──────────┐       │
│  │Vault│ │Todos│ │ GCal │ │Scheduler│ │ Telegram │       │
│  │(MCP)│ │(MCP)│ │(MCP) │ │         │ │  Bridge  │       │
│  └─────┘ └─────┘ └──────┘ └─────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

**Voice path:** Microphone → wake word detection → speech-to-text → orchestrator retrieves relevant memories → Claude agent processes and calls tools → text-to-speech → speaker.

**Telegram path:** Phone → Telegram API → bridge → orchestrator retrieves memories → same Claude agent → bridge → phone.

**Proactive path:** Scheduler fires → orchestrator → Claude agent (gathers context) → spoken aloud + sent to Telegram.

## Services

| Service | Technology | What it does |
|---------|-----------|--------------|
| Wake word | openWakeWord | Listens continuously for a custom trigger word. ~2% CPU. |
| Speech-to-text | faster-whisper | Transcribes speech to text. Multilingual (EN/RO). Local. |
| Text-to-speech | piper | Converts agent responses to spoken audio. Local. |
| Orchestrator | Python (custom) | Manages session states, assembles context with memory, routes requests. |
| Agent | claude-agent-sdk | The brain. Calls tools, reasons about tasks, generates responses. |
| Telegram bridge | python-telegram-bot | Connects the assistant to a private Telegram bot. Polling mode — no public IP needed. |
| Notes | @bitbonsai/mcpvault | MCP server for an Obsidian-style markdown vault. Grocery lists, ideas, journal, reference. |
| Todos | Vikunja + custom MCP | Self-hosted task manager with priorities, due dates, and projects. |
| Calendar | @cocal/google-calendar-mcp | Google Calendar integration via OAuth2. Create, read, update events. |
| Scheduler | APScheduler + SQLite | One-off and recurring reminders. Fires proactive agent wake-ups. |
| Memory | SQLite + FTS5 | Persistent knowledge store. Orchestrator retrieves relevant facts every turn. |

## Memory system

Memory has two tiers:

**Short-term:** The last 20 messages from the current conversation are always included. This handles follow-ups like "no, the other one" or "change that to Thursday." Cleared when the session ends.

**Long-term:** A SQLite database of facts the agent has learned about you — preferences, people, ongoing projects, decisions. On every turn, the orchestrator proactively searches this store and injects relevant memories into the context *before* the agent runs. The agent never has to decide to search its own memory — relevant knowledge is always there.

Three retrieval passes run on each turn:
1. **User profile** — a compact summary of core facts, always present (~300–500 tokens)
2. **Contextual search** — FTS5 full-text search using the current message as query (top 10 matches)
3. **Recency** — everything stored in the last 48 hours, regardless of keyword match

The agent can write new memories (`remember`) and delete them on request (`forget`), but never needs to search — that's the orchestrator's job.

## Conversation behaviour

The assistant uses a session state machine:

```
IDLE ──(wake word)──→ RECORDING ──(1.5s silence)──→ PROCESSING ──(response spoken)──→ HOT
                                                                                      │
HOT ──(user speaks within 30s, no wake word needed)──→ RECORDING                      │
HOT ──(30s silence)──→ IDLE                                                           │
                                                                                      │
IDLE ──(scheduler fires)──→ PROACTIVE ──(response spoken)──→ HOT ─────────────────────┘
```

During a **hot session**, the wake word isn't needed — just speak and the assistant picks it up. The 30-second timer resets with each exchange, allowing natural multi-turn conversation. Audio cues (chimes, clicks) signal when the assistant starts and stops listening.

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Hardware | Raspberry Pi 5, 8GB | Runs Whisper `small` model in 3–5s. aarch64 support for all dependencies. |
| Agent | claude-agent-sdk | Same tooling as Claude Code. Built-in filesystem, web search, and MCP support. aarch64 wheel on PyPI. |
| Wake word | openWakeWord | Custom wake words with synthetic training data. Low CPU. |
| STT | faster-whisper | C++ Whisper port. Fast on ARM. Auto-detects language. |
| TTS | piper | Local, fast, multiple language voices. |
| Notes | Obsidian vault via mcpvault | Plain markdown files. No app needed on Pi. 14 MCP tools for CRUD + search. |
| Todos | Vikunja | Go binary, Docker image, full REST API, SQLite or Postgres. |
| Calendar | Google Calendar MCP | OAuth2 with refresh token. Multi-calendar, conflict detection. |
| Scheduler | APScheduler | Python library. Cron expressions. Persistent job store in SQLite. |
| Memory | SQLite + FTS5 | Microsecond full-text search. No external dependencies. |
| Remote | Telegram Bot API | Free, polling mode (no public IP), works on iPhone. |
| Containers | Docker Compose | One command to start everything. Volumes for persistence. |

## Project structure

```
pi-assistant/
├── README.md
├── SPEC.md                    # Full feature specification
├── docker-compose.yml
├── .env.example
│
├── orchestrator/              # Session manager + memory retrieval
│   ├── Dockerfile
│   ├── main.py
│   ├── session.py             # State machine (idle/recording/hot)
│   ├── memory.py              # SQLite FTS5 store + 3-pass retrieval
│   └── context.py             # Assembles prompt + memories + history
│
├── agent/                     # Claude agent configuration
│   ├── Dockerfile
│   ├── main.py
│   ├── system_prompt.py
│   └── tools/
│       ├── memory_tools.py    # remember + forget
│       └── scheduler_tools.py
│
├── telegram-bridge/           # Telegram bot
│   ├── Dockerfile
│   └── main.py
│
├── vikunja-mcp/               # Vikunja REST API wrapper
│   ├── Dockerfile
│   └── main.py
│
├── scheduler/                 # APScheduler service
│   ├── Dockerfile
│   └── main.py
│
├── audio/                     # Host services (not containerised)
│   ├── wake_word.py
│   ├── stt.py
│   ├── tts.py
│   └── sounds/                # Chime, click, buzz audio files
│
├── vault/                     # Obsidian vault (markdown files)
│   ├── Grocery/
│   ├── Ideas/
│   ├── Journal/
│   ├── Projects/
│   ├── Reference/
│   ├── Meetings/
│   └── Inbox/
│
└── data/                      # Persistent data (Docker volumes)
    ├── memory.db
    ├── schedules.db
    ├── vikunja.db
    └── gcal-credentials/
```

## Build phases

| Phase | What | Status |
|-------|------|--------|
| 1 | Core voice loop — wake word, STT, agent, TTS, hot sessions | Planned |
| 2 | Notes (vault MCP) and todos (Vikunja + MCP wrapper) | Planned |
| 3 | Google Calendar + scheduler with proactive reminders | Planned |
| 4 | Telegram bridge for remote access | Planned |
| 5 | Long-term memory with proactive retrieval | Planned |
| 6 | Polish — error handling, health checks, prompt tuning | Planned |
| 7 | Extensions — Slack, Home Assistant, email, semantic search | Optional |

## Prerequisites

- Raspberry Pi 5 (8GB recommended) with 64-bit Raspberry Pi OS
- USB microphone and speaker
- Stable internet connection (for Claude API)
- Anthropic API key
- Google Cloud project with Calendar API enabled (for calendar features)
- Telegram account (for remote access)

## Quick start

```bash
# Clone the repo
git clone https://github.com/your-username/pi-assistant
cd pi-assistant

# Copy and edit environment variables
cp .env.example .env
# Add: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID

# Start Docker services
docker compose up -d

# Install and start host audio services
cd audio
pip install -r requirements.txt
python wake_word.py &
```

See [SPEC.md](SPEC.md) for the full feature specification including memory system design, session state machine, error handling, and security model.

## Custom code

The project is ~970 lines of custom Python glue. Everything else is off-the-shelf:

| Custom service | ~Lines |
|---------------|--------|
| Orchestrator (sessions + memory + context) | 350 |
| Vikunja MCP wrapper | 200 |
| Scheduler service | 150 |
| Audio pipeline glue | 150 |
| Telegram bridge | 120 |