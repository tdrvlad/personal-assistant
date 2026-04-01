# Pi Assistant — Full Feature Specification

A voice-activated personal assistant running on a Raspberry Pi 5, powered by Claude via the Agent SDK, with a Telegram text interface for remote access. The system runs continuously, listening for a wake word, and can also proactively speak to deliver reminders and scheduled information.

---

## 1. Hardware & environment

- **Device:** Raspberry Pi 5, 8GB RAM, 64-bit Raspberry Pi OS
- **Microphone:** USB microphone or ReSpeaker array (far-field pickup)
- **Speaker:** Connected via 3.5mm jack or USB DAC
- **Network:** Stable Wi-Fi or Ethernet (required for Claude API)
- **Storage:** microSD or USB SSD for OS + Docker volumes
- **Runtime:** Runs 24/7, always listening for wake word

---

## 2. Architecture

The system is decomposed into microservices. Audio services run on the host (bare metal) for direct hardware access. Everything else runs in Docker containers.

### 2.1 Host services (bare metal)

| Service | Technology | Role |
|---------|-----------|------|
| Wake word detection | openWakeWord | Continuously monitors microphone for trigger word. Low CPU (~2%). |
| Speech-to-text | faster-whisper (`small` model) | Transcribes recorded audio to text. Runs on-demand when triggered. |
| Text-to-speech | piper | Converts agent text responses to spoken audio. Plays through speaker. |

### 2.2 Docker containers

| Container | Technology | Role |
|-----------|-----------|------|
| Orchestrator | Python (custom) | Session state machine. Routes voice and Telegram input to agent. Handles memory retrieval and context assembly before each agent call. |
| Claude agent | claude-agent-sdk | Core intelligence. Receives assembled context (system prompt + memories + conversation), uses tools, returns text responses. |
| Telegram bridge | python-telegram-bot (custom) | Polls Telegram API for messages. Routes to/from orchestrator. Sends proactive notifications. |
| Google Calendar MCP | @cocal/google-calendar-mcp | CRUD operations on Google Calendar. OAuth2 auth with stored refresh token. |
| Obsidian vault MCP | @bitbonsai/mcpvault | Read, write, search, tag, and organise markdown notes in the vault directory. |
| Vikunja | vikunja/vikunja | Self-hosted todo/task management app with REST API. |
| Vikunja MCP wrapper | Python (custom) | Translates MCP tool calls into Vikunja REST API requests. |
| Scheduler | Python + APScheduler (custom) | Stores reminders and recurring triggers. Fires events that wake the agent proactively. |

### 2.3 Persistence (Docker volumes)

| Volume | Contents |
|--------|----------|
| `./vault/` | Obsidian vault — all markdown notes, organised by folder |
| `./vikunja-data/` | Vikunja database and file uploads |
| `./schedules.db` | Scheduler's SQLite database of reminders and cron triggers |
| `./memory.db` | SQLite database with FTS5 index for long-term agent memory |
| `./gcal-credentials/` | Google OAuth credentials and refresh token |

### 2.4 Request flow

There is no concurrent access scenario — the user is either at home (voice) or away (Telegram), never both simultaneously. The only overlap is the scheduler firing while the user is mid-Telegram-conversation, which simply delivers a second Telegram message. All requests are processed sequentially — no queue or locking needed.

```
Voice path:   Mic → Wake word → STT → Orchestrator → [memory retrieval] → Agent → TTS → Speaker
Telegram path: Phone → Telegram API → Bridge → Orchestrator → [memory retrieval] → Agent → Bridge → Phone
Proactive path: Scheduler → Orchestrator → [memory retrieval] → Agent → TTS + Telegram
```

---

## 3. Voice interface

### 3.1 Wake word

- Custom wake word trained with openWakeWord (configurable, default: TBD by user)
- Detection runs continuously with minimal CPU usage
- On detection: play a short confirmation chime (subtle, <0.5s) to signal the assistant is listening

### 3.2 Speech recording

- After wake word detection, the system begins recording from the microphone
- Recording ends when **1.5 seconds of silence** is detected (voice activity detection via webrtcvad or silero-vad)
- Maximum recording duration: 30 seconds (safety cap to avoid infinite recordings)
- Audio is passed to faster-whisper for transcription

### 3.3 Speech-to-text

- Model: faster-whisper with `small` model (balance of accuracy and speed on Pi 5)
- **Multilingual:** Supports both English and Romanian — auto-detected per utterance by Whisper
- Expected latency: 3–5 seconds on Pi 5
- Output: plain text transcription passed to the orchestrator

### 3.4 Text-to-speech

- Engine: piper (local, open-source, fast)
- Voice: configurable; one English voice and one Romanian voice, auto-selected based on the language of the agent's response
- Output: played through connected speaker
- Used for both reactive responses (user-initiated) and proactive announcements (scheduler-initiated)

### 3.5 Audio feedback cues

| Event | Sound |
|-------|-------|
| Wake word detected | Short rising chime — "I'm listening" |
| Recording ended (silence detected) | Soft click — "Processing" |
| Session cooldown expired | Short falling tone — "Session closed" |
| Proactive reminder incoming | Gentle double-chime — "Attention" before speaking |
| Error / offline | Low buzz — "Something went wrong" |

---

## 4. Conversation session management

### 4.1 Session states

```
IDLE → (wake word) → RECORDING → (silence) → PROCESSING → (response spoken) → HOT
HOT → (user speaks within 30s) → RECORDING  [no wake word needed]
HOT → (30s silence) → IDLE
IDLE → (scheduler fires) → PROACTIVE → (response spoken) → HOT
```

### 4.2 Idle state

- Wake word engine is active, listening continuously
- All other audio processing is inactive (saves CPU)
- Agent is not loaded — no API calls

### 4.3 Recording state

- Microphone audio is captured to a buffer
- Voice activity detection monitors for 1.5s of continuous silence to end recording
- 30-second hard cap on recording duration

### 4.4 Processing state

- Recorded audio is transcribed via faster-whisper
- Transcribed text is sent to the orchestrator
- Orchestrator assembles full context (see section 8) and calls the Claude agent
- Agent processes, calls tools as needed, returns text response
- Response is converted to speech via piper and played
- During processing, a subtle ambient indicator could play (optional — e.g., very quiet ticking or simply silence)

### 4.5 Hot session state

- After speaking a response, the system enters a 30-second hot window
- During this window, any detected speech triggers recording **without requiring the wake word**
- The 30-second timer **resets** each time a new exchange completes
- This allows natural multi-turn conversation
- Conversation history is preserved throughout the hot session as part of the sliding window
- After 30 seconds of silence, the session closes with an audio cue and returns to idle

### 4.6 Proactive state

- Triggered by the scheduler service (not by user voice)
- The system plays an attention chime, then speaks the agent's message via TTS
- After speaking, enters hot session so the user can respond immediately
- If no response within 30 seconds, returns to idle
- The same message is also sent to the Telegram chat as a push notification

---

## 5. Telegram interface

### 5.1 Setup

- Bot created via Telegram @BotFather
- Runs in **polling mode** (no public IP or HTTPS required)
- Restricted to a single Telegram user ID (owner only)

### 5.2 Capabilities

- **Text input/output only** (no voice on Telegram)
- Messages sent to the bot are routed to the orchestrator, which assembles context and calls the same Claude agent with the same tools
- Agent responses are sent back as Telegram messages
- All interactions (voice and Telegram) share the same:
  - Obsidian vault
  - Vikunja todos
  - Google Calendar
  - Long-term memory store
  - Scheduler

### 5.3 Proactive messages

- When the scheduler fires a reminder, it is delivered to Telegram as a push notification in addition to being spoken aloud at home
- The user can reply to proactive messages in Telegram to continue the conversation

### 5.4 Conversation context

- Telegram conversations maintain their own sliding window (last K messages, see section 8)
- Long-term memory is shared with voice sessions

---

## 6. Tools & integrations

### 6.1 Obsidian vault (notes & knowledge)

**MCP server:** @bitbonsai/mcpvault
**Purpose:** All notes, lists, ideas, and reference material

The vault is a directory of markdown files on the Pi's filesystem. No Obsidian application needs to run — the MCP server operates directly on the files. The user interacts with notes exclusively through voice or Telegram; no separate app is needed on the phone.

**Vault folder structure** (configurable, suggested default):

```
vault/
├── Grocery/          # Shopping lists
├── Ideas/            # Random thoughts, brainstorms
├── Journal/          # Daily entries, reflections
├── Projects/         # Project-specific notes
├── Reference/        # How-tos, saved info, recipes
├── Meetings/         # Meeting notes
└── Inbox/            # Unsorted quick captures
```

**Behaviours:**
- "Add eggs and milk to my grocery list" → appends to `Grocery/shopping.md`
- "I have an idea about the balcony garden" → creates or appends to `Ideas/garden.md`
- "What's on my grocery list?" → reads and speaks `Grocery/shopping.md`
- "Note that the plumber's number is 07XX XXX XXX" → saves to `Reference/contacts.md` or similar
- Agent decides the appropriate file and folder based on content. If unclear, it asks.
- Agent can search across the entire vault when answering questions ("did I write anything about X?")

### 6.2 Vikunja (todos & tasks)

**Service:** vikunja/vikunja Docker image
**MCP wrapper:** Custom Python service translating tool calls to Vikunja REST API

**Capabilities:**
- Create tasks with title, due date, priority, project assignment
- List tasks filtered by: due today, due this week, overdue, by project, by priority
- Mark tasks as complete
- Edit tasks (change due date, priority, description)
- Create and manage projects (groups of related tasks)

**Behaviours:**
- "Remind me to call the dentist tomorrow" → creates a task due tomorrow + schedules a proactive reminder (see scheduler)
- "What do I need to do today?" → lists tasks due today across all projects
- "Mark 'buy birthday gift' as done" → completes the task
- Tasks are distinct from notes: tasks have state (open/done), due dates, and priority. Notes are freeform.

### 6.3 Google Calendar

**MCP server:** @cocal/google-calendar-mcp
**Auth:** OAuth2 with stored refresh token (one-time browser setup)

**Capabilities:**
- List upcoming events (today, this week, specific date range)
- Create events with title, time, duration, location, description
- Update and delete events
- Check free/busy availability
- Detect scheduling conflicts

**Behaviours:**
- "What's on my calendar today?" → reads today's events
- "Schedule a meeting with Alex on Friday at 2pm for one hour" → creates event
- "Am I free Thursday afternoon?" → checks availability
- "Move my 3pm to 4pm" → updates event time

### 6.4 Scheduler (reminders & triggers)

**Service:** Custom Python + APScheduler + SQLite
**Purpose:** Time-based agent activations — both one-off reminders and recurring schedules

**Capabilities:**
- **One-off reminders:** "Remind me to take out the bins at 8pm" → scheduler fires at 8pm, agent speaks the reminder and sends to Telegram
- **Recurring triggers:** "Every Monday morning at 9am, read me my calendar for the week" → cron-style recurring job that prompts the agent with a predefined instruction
- **Contextual triggers:** The scheduled prompt can instruct the agent to gather information before speaking — e.g., "Check today's calendar and todos, then give me a morning briefing"
- Reminders can be listed, edited, and cancelled via voice or Telegram
- All reminders are persisted in SQLite (survive restarts)

**Trigger types:**

| Type | Example | Storage |
|------|---------|---------|
| One-off | "Remind me at 6pm to pick up dry cleaning" | datetime + message |
| Daily | "Every day at 8am give me a briefing" | cron expression + agent prompt |
| Weekly | "Every Sunday evening, summarise my week" | cron expression + agent prompt |
| Custom cron | "First Monday of every month, remind me to pay rent" | cron expression + message |

### 6.5 Memory tools (remember & forget)

**Purpose:** Allow the agent to write to and delete from the long-term memory store

These are the only memory operations the agent controls directly. Retrieval is handled proactively by the orchestrator (see section 8). The agent has two tools:

- **`remember(content, category, tags)`** — stores a fact, preference, decision, or contextual note. The agent uses this when the user shares personal information, makes a decision, or states a preference. The agent does not announce when it stores a memory — it does so quietly.
- **`forget(query)`** — searches memory for entries matching the query and deletes them. Used only when the user explicitly asks to forget something. The agent confirms what it's deleting before removing.

### 6.6 Filesystem tools

**Source:** Built into claude-agent-sdk (Read, Write, Edit, Bash, Glob)
**Scope:** Configurable working directory on the Pi (e.g., `~/documents`)

**Capabilities:**
- Read file contents
- Create and write new files
- Edit existing files
- List directory contents
- Run shell commands (restricted — no destructive commands)

### 6.7 Web search & web fetch

**Source:** Built into claude-agent-sdk
**Purpose:** Real-time information lookup

**Behaviours:**
- "What's the weather in Bucharest?" → web search
- "Find a risotto recipe" → web search, optionally save result to vault
- "What's the latest news about X?" → web search and summarise

### 6.8 Slack (optional, phase 2)

**MCP server:** Community Slack MCP
**Purpose:** Work communication integration

**Capabilities:**
- Read recent messages from channels
- Send messages to channels or DMs
- Search Slack history

---

## 7. Agent behaviour & personality

### 7.1 System prompt

The agent receives a detailed system prompt defining:
- Its role as a personal assistant
- The user's name and preferences
- Available tools and when to use each one
- Vault folder structure conventions
- Language preferences (responds in the same language the user spoke)
- Tone: conversational, concise, helpful — not robotic or overly formal
- For voice responses: keep answers short and spoken-friendly (no markdown, no bullet lists, no long paragraphs). Use natural sentence structure.
- For Telegram responses: can be slightly more detailed since the user is reading, but still concise
- Memory guidelines (see section 8.4)
- The interface currently in use (voice or Telegram) is passed as a parameter so the agent can adapt its response style

### 7.2 Language handling

- The agent responds in the **same language** the user spoke
- If the user speaks Romanian, the agent responds in Romanian
- If the user speaks English, the agent responds in English
- Whisper auto-detects the language per utterance
- Piper TTS selects the appropriate voice model based on the detected language of the response
- Tool interactions (calendar events, task names, note content) are stored in whatever language the user used

### 7.3 Response style — voice vs. text

| Aspect | Voice responses | Telegram responses |
|--------|----------------|-------------------|
| Length | 1–3 sentences preferred, max ~30 seconds spoken | Can be longer, up to a few paragraphs |
| Formatting | Plain spoken language, no markdown | Light markdown (bold, lists) allowed |
| Confirmation | Brief: "Done, added to your grocery list" | Can include more detail: "Added eggs and milk to Grocery/shopping.md" |
| Questions | Asks one clarifying question max | Can ask more detailed follow-ups |
| Lists | Reads top 3–5 items, asks "want to hear more?" | Shows full list |

---

## 8. Memory system

The memory system has two tiers: a short-term sliding window of recent messages, and a long-term knowledge store that the orchestrator queries proactively on every turn.

The key design principle is that **retrieval is proactive and handled by the orchestrator, not the agent**. The agent never needs to decide to search its own memory — relevant knowledge is selected and injected into the context before the agent sees the conversation. This eliminates the problem of the agent not knowing what it knows.

### 8.1 Tier 1 — Sliding window (short-term, automatic)

- Every agent call includes the **last K messages** (configurable, default: K=20) from the current session
- This provides immediate conversational context for follow-ups ("no, the other one", "change that to Thursday")
- Voice sessions: the window spans the current hot session. When the session closes (30s cooldown), the window is cleared
- Telegram sessions: the window spans the last K messages in the chat, regardless of time gaps
- No intelligence needed — this is just raw conversation history appended to the context

### 8.2 Tier 2 — Long-term memory store (persistent, proactive)

**Storage:** SQLite database with FTS5 full-text search index

**Schema:**
```sql
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,        -- the fact or knowledge
    category    TEXT NOT NULL,        -- fact | preference | context | decision
    tags        TEXT,                 -- comma-separated, e.g. "travel,ana"
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source      TEXT                  -- "voice" or "telegram"
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, category, tags,
    content=memories, content_rowid=id
);
```

**Memory categories:**
- **fact** — stable personal information: "User's dentist is Dr. Popescu on Str. Victoriei", "User's partner is named Ana"
- **preference** — likes, dislikes, habits: "Prefers oat milk", "Likes meetings before noon", "Doesn't eat cilantro"
- **context** — ongoing situations or projects: "Planning a trip to Vienna in June 2026", "Renovating the kitchen"
- **decision** — choices the user has made: "Chose grey metro tiles for the kitchen backsplash on March 15"

### 8.3 Proactive memory injection (orchestrator responsibility)

On **every turn** (voice or Telegram), before calling the Claude agent, the orchestrator assembles the context by running three retrieval passes against the memory store:

**Pass 1 — User profile (always present):**
A curated summary block (~300–500 tokens) containing core facts about the user: name, location, language preferences, key people, active projects, and recurring patterns. This block is always injected so the agent never feels amnesiac. The profile is rebuilt periodically (see section 8.5).

**Pass 2 — Contextual search (per-turn):**
The orchestrator takes the user's current message and runs it as a full-text search query against the FTS5 index. The top N results (configurable, default: N=10) are injected as a `[RELEVANT MEMORIES]` block. This handles the common case where the user's words overlap with stored knowledge — "what tiles did I pick?" matches memories containing "tiles".

**Pass 3 — Recency window (per-turn):**
All memories created or updated in the **last 48 hours** are included regardless of whether they match the current query. This ensures that recent conversations remain "top of mind" even if the current message doesn't share keywords with them. The 48-hour window is configurable.

Results from all three passes are **deduplicated** (by memory ID) and assembled into the context.

**Assembled context sent to the agent on each turn:**

```
[SYSTEM PROMPT]
  Role, personality, available tools, vault structure, memory guidelines,
  current interface (voice|telegram)...

[USER PROFILE]
  Name: ...
  Location: Bucharest
  Languages: English, Romanian
  Partner: Ana
  Active projects: kitchen renovation, Vienna trip June 2026
  Preferences: oat milk, meetings before noon...

[RELEVANT MEMORIES]
  - (2026-03-15, decision) Chose grey metro tiles for kitchen backsplash
  - (2026-03-28, fact) Dentist appointment with Dr. Popescu, Str. Victoriei
  - (2026-04-01, context) Booked Airbnb in Vienna for June 12-16
  (from FTS5 match + recency window, deduplicated, max ~10 entries)

[CONVERSATION HISTORY]
  user: ...
  assistant: ...
  user: ...
  (last K messages from sliding window)

[CURRENT MESSAGE]
  user: "..."
```

### 8.4 Agent memory tools (write & delete only)

The agent has two memory tools. It does **not** have a recall/search tool — retrieval is entirely handled by the orchestrator before the agent runs.

**`remember(content, category, tags)`**
- Stores a new entry in the memory database
- The system prompt instructs the agent when to use this:
  - User shares personal information (names, addresses, numbers)
  - User states a preference ("I prefer...", "I don't like...")
  - User makes a decision ("Let's go with the grey tiles")
  - User mentions an ongoing project or plan
  - User explicitly asks the agent to remember something
- The agent does **not** announce when it stores a memory — it does so quietly alongside its normal response
- The agent does **not** store trivial conversational filler or restate things already in memory

**`forget(query)`**
- Searches memory for entries matching the query
- Returns matching entries to the agent for confirmation
- Deletes confirmed entries
- Used only when the user explicitly asks: "Forget what I told you about the surprise party"
- The agent always confirms what it's about to delete before removing

### 8.5 User profile maintenance

The user profile is a compact summary that is always injected into the context. It is not hand-written — it is generated and maintained automatically:

- **Initial creation:** After the first ~10 memory entries are stored, the orchestrator calls the agent with a special prompt: "Based on these memories, generate a concise user profile summary." The result is stored as the profile.
- **Periodic refresh:** A scheduled task (e.g., weekly) re-generates the profile from all current memories. This keeps it current as facts change — "User was choosing tiles" becomes "User chose grey metro tiles" after the decision is stored.
- **Manual trigger:** The user can say "Update my profile" to force a refresh.
- **Token budget:** The profile should stay under 500 tokens. If it grows beyond this, the refresh task should prioritise recent and frequently-accessed facts.

### 8.6 Memory lifecycle example

**Session 1 (voice, March 10):**
```
User: "I'm thinking of going to Vienna in June with Ana"
Orchestrator: searches memory → no relevant matches (new topic)
Agent: responds conversationally, quietly calls remember(
    content="Planning a trip to Vienna in June 2026 with Ana",
    category="context",
    tags="travel,ana"
)
```

**Session 2 (Telegram, March 25):**
```
User: "Book a hotel in Vienna"
Orchestrator: FTS5 search "hotel Vienna" → matches memory about Vienna trip
Orchestrator: injects [RELEVANT MEMORIES: "Planning a trip to Vienna in June 2026 with Ana"]
Agent: sees the memory in context → "I remember you're going in June with Ana.
       How many nights, and do you have a budget in mind?"
```

**Session 3 (voice, April 2):**
```
User: "What was that city I wanted to visit?"
Orchestrator: FTS5 search "city visit" → partial match on "trip to Vienna"
Orchestrator: recency window also catches the Vienna memory (if within 48h)
Agent: "You're planning a trip to Vienna in June with Ana."
```

**Session 4 (Telegram, April 10):**
```
User: "Forget about the Vienna trip, we cancelled it"
Agent: searches memory → finds Vienna entry → confirms → calls forget()
Agent: "Done, I've forgotten about the Vienna trip."
```

### 8.7 FTS5 limitations and future upgrade path

SQLite FTS5 uses keyword matching. It works well when the user's query and stored memories share words. It may miss semantic matches where no keywords overlap — e.g., "what did I decide about the flooring?" when the memory says "chose grey metro tiles for the kitchen backsplash."

Mitigations in the current design:
- The 48-hour recency window catches recent memories regardless of keyword overlap
- The always-present user profile covers major ongoing topics
- In practice, people tend to reuse the same words when referring to the same topics

Future upgrade (if FTS5 proves insufficient):
- Add a local embedding model (e.g., `all-MiniLM-L6-v2`, ~80MB) for semantic search as a second retrieval path alongside FTS5
- The orchestrator would run both keyword and semantic searches, merge and deduplicate results
- This adds ~200ms of latency per query on a Pi 5, which is acceptable

---

## 9. Error handling & edge cases

### 9.1 Internet outage

- If the Claude API is unreachable, the agent announces via TTS: "I'm offline right now. I'll try again shortly."
- Voice commands during an outage are **not queued** (user should retry when back online)
- Telegram messages during an outage: the bridge retries the agent call 3 times with backoff, then replies "I'm having trouble connecting. Try again in a few minutes."
- The wake word and STT continue to function (they're local) — only the agent call fails

### 9.2 Transcription errors

- If Whisper produces gibberish or an empty transcription, the agent responds: "Sorry, I didn't catch that. Could you say it again?"
- If the agent's response doesn't make sense in context, the user can say "That's not what I meant" and the agent re-prompts

### 9.3 Tool failures

- If an MCP server is unreachable (e.g., Vikunja container is down), the agent reports the issue: "I can't reach the todo service right now."
- Agent does not hallucinate results — it explicitly states when a tool fails
- Docker healthchecks restart crashed containers automatically

---

## 10. Security & privacy

- **Single-user system:** no authentication beyond Telegram user ID whitelist
- **Local-first:** all data (vault, todos, memory, schedules) stored on the Pi's filesystem
- **API key security:** `ANTHROPIC_API_KEY` and other secrets stored in `.env`, never exposed
- **Google OAuth tokens:** stored in a Docker volume, refresh token auto-renews
- **Telegram bot:** restricted to owner's user ID; all other messages are silently ignored
- **Filesystem tools:** restricted to a configurable working directory (no access to system files)
- **Bash tool:** restricted — dangerous commands (rm -rf, sudo, etc.) blocked via agent SDK hooks
- **No cloud sync of notes or data** — all data stays on the Pi

---

## 11. Deployment & operations

### 11.1 Startup

- `docker compose up -d` brings up all containerised services
- Host services (wake word, STT, TTS) run as systemd services
- On boot, the Pi auto-starts all services
- Startup health check: orchestrator pings each MCP server and reports status via TTS ("All systems online" or "Calendar service is unavailable")

### 11.2 Monitoring

- Each container has a Docker healthcheck
- Orchestrator exposes a simple `/health` endpoint listing service status
- Optional: daily summary pushed to Telegram: "System status: all 8 services healthy, uptime 14 days"

### 11.3 Updates

- Docker images updated via `docker compose pull && docker compose up -d`
- Custom services updated via git pull + rebuild
- Vault and data volumes persist across updates

---

## 12. Project phases

### Phase 1 — Core voice loop
- Wake word → STT → Claude agent → TTS
- Basic conversation with hot session / cooldown
- Filesystem tools working
- Audio feedback cues

### Phase 2 — Notes & todos
- Obsidian vault MCP connected
- Vikunja deployed + MCP wrapper built
- Agent can create notes, manage todos

### Phase 3 — Calendar & scheduling
- Google Calendar MCP connected (OAuth setup)
- Scheduler service built
- Proactive reminders working (voice)

### Phase 4 — Telegram
- Telegram bridge built and connected
- Remote access to all tools via text chat
- Proactive notifications delivered to both voice and Telegram

### Phase 5 — Memory
- SQLite + FTS5 memory store created
- `remember` and `forget` tools exposed to agent
- Orchestrator performs proactive 3-pass retrieval on every turn
- User profile auto-generation and periodic refresh
- System prompt tuned with memory guidelines

### Phase 6 — Polish & hardening
- Audio cues refined
- Startup health checks
- Error handling edge cases tested
- System prompt tuned based on real usage
- Token budget monitoring (ensure context assembly stays within limits)

### Phase 7 — Extensions (optional)
- Slack MCP
- Home Assistant MCP
- Email MCP
- Semantic search via local embedding model
- Additional custom tools as needed

---

## 13. Technology reference

Quick reference of all technologies and versions:

| Component | Technology | Notes |
|-----------|-----------|-------|
| Hardware | Raspberry Pi 5, 8GB | 64-bit Raspberry Pi OS |
| Containerisation | Docker + Docker Compose | All services except audio |
| Agent SDK | claude-agent-sdk (Python) | `pip install claude-agent-sdk`, aarch64 wheel available |
| Wake word | openWakeWord | Custom wake word training supported |
| STT | faster-whisper (`small` model) | Multilingual (EN + RO), ~3–5s latency on Pi 5 |
| TTS | piper | Separate EN and RO voice models |
| Notes | @bitbonsai/mcpvault | MCP server for Obsidian-style vault, no Obsidian app needed |
| Todos | Vikunja (vikunja/vikunja) | Self-hosted, Go-based, REST API with Swagger docs |
| Todos MCP | Custom Python wrapper | Translates MCP tool calls to Vikunja REST API |
| Calendar | @cocal/google-calendar-mcp | OAuth2, multi-calendar, Node.js |
| Scheduler | APScheduler + SQLite | Python, cron expressions, persistent jobs |
| Memory | SQLite + FTS5 | Full-text search, ~microsecond query time |
| Telegram | python-telegram-bot | Polling mode, no public IP needed |
| Voice detection | webrtcvad or silero-vad | Silence detection for recording boundaries |

### Estimated custom code

| Service | Approx. lines |
|---------|---------------|
| Orchestrator (session manager + memory retrieval + context assembly) | ~350 |
| Telegram bridge | ~120 |
| Vikunja MCP wrapper | ~200 |
| Scheduler service | ~150 |
| Audio glue (wake word → STT → TTS pipeline) | ~150 |
| **Total** | **~970** |
