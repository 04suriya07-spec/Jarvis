# Javris vs Iron Man JARVIS — Master Implementation Plan
**Date:** 2026-05-07 | **Current Score: 47/100 → Target: 95/100**

---

## Section 1: Current State Scorecard

| Module | File | Status | Score |
|--------|------|--------|-------|
| Multi-LLM Router (UCB1 + hedging) | `core/llm/router.py` | Complete | 10/10 |
| Groq + Cerebras providers | `core/llm/providers.py` | Complete | 10/10 |
| Semantic memory (ChromaDB) | `core/vector_memory.py` | Complete | 8/10 |
| Ambient OS watcher | `core/ambient.py` | Complete | 8/10 |
| Dual autonomy loop (30s/10min) | `core/autonomy.py` | Complete | 7/10 |
| Gmail IMAP + SMTP | `skills/email_skill.py` | Complete | 9/10 |
| Personality engine | `core/personality.py` | Complete | 7/10 |
| Intelligence engine | `core/intelligence.py` | Complete | 7/10 |
| Memory (ring + SQLite) | `core/memory.py` | Complete | 7/10 |
| JARVIS HUD frontend | `frontend/index.html` | Complete | 8/10 |
| WebSocket unified `/ws` | `server/app.py` | Complete | 8/10 |
| System vitals `/api/system` | `server/app.py` | Complete | 8/10 |
| Weather skill | `skills/weather.py` | Complete | 7/10 |
| News skill | `skills/news.py` | Complete | 7/10 |
| Finance skill | `skills/finance.py` | Complete | 7/10 |
| Web search (SerpAPI) | `skills/web_search.py` | Complete | 7/10 |
| Music skill | `skills/music.py` | Partial — no Spotify API | 4/10 |
| Gemini Live (audio/video) | `core/gemini_live.py` | Built, untested | 3/10 |
| Calendar skill | `skills/life/calendar_skill.py` | Local only, no Google Cal | 4/10 |
| Code runner | `skills/code_runner.py` | Basic exec only | 4/10 |
| Telegram/Discord notify | `skills/telegram_notify.py` | Stubs | 3/10 |
| GitHub skill | `skills/github.py` | Partial | 4/10 |
| Voice pipeline | `voice/` | Basic Whisper + edge-tts | 4/10 |

**Overall Score: 47 / 100**

---

## Section 2: Gap Analysis — What Real JARVIS Can Do That We Cannot

### Perception Gaps
- No webcam presence detection (JARVIS knows when Tony walks in)
- No screen OCR (cannot read what is on screen unless typed)
- No microphone hot-word wake without Porcupine key
- No emotion/tone detection from voice
- No multi-monitor awareness

### Intelligence Gaps
- No self-correcting chain-of-thought (JARVIS re-plans mid-task)
- No parallel multi-agent execution (cannot split research + code + search simultaneously)
- No deep episodic memory (does not remember "last Thursday we discussed X")
- No automatic code debugging loop (write, run, see error, fix, re-run)
- No relationship model (does not know who "Pepper" or "Rhodey" are to the user)

### Interface Gaps
- No desktop overlay / always-on HUD (currently browser tab only)
- No mobile PWA app
- No custom voice (uses edge-tts stock voices)
- No 3D particle visualization
- No proactive interrupts based on calendar events

### Integration Gaps
- No Google Calendar real-time sync
- No Spotify Web API (only local TasteDive recommendations)
- No WhatsApp integration
- No smart document reading (PDF, Word, screenshots)
- No health/fitness API integration
- No smart home (HomeAssistant/Matter)

### Autonomy Gaps
- Autonomy loop does not self-heal failing skills
- No overnight research agent
- No scheduled reports delivered at wake-up
- Break reminders not yet wired to calendar awareness

---

## Section 3: Phase 1 — Foundation Fixes (47% → 62%)
**Timeline: 1-2 weeks | Focus: Activate built infrastructure + fill critical skill gaps**

### 3.1 Activate Gemini Live (file exists, needs wiring)
**File:** `core/gemini_live.py` (already written — 15,814 bytes)

Changes needed:
- Wire `GeminiLiveSession` into `server/app.py` as `/ws/gemini-live`
- Add frontend toggle button: "Switch to Live Mode"
- Test full-duplex audio with Google API key pool (3 keys available)

```python
# server/app.py addition
from core.gemini_live import GeminiLiveSession

@app.websocket("/ws/gemini-live")
async def gemini_live_ws(websocket: WebSocket):
    await websocket.accept()
    session = GeminiLiveSession(api_key=cfg.google_api_key_1)
    async with session.connect() as live:
        async for audio_chunk in websocket.iter_bytes():
            response = await live.send_audio(audio_chunk)
            await websocket.send_bytes(response)
```

### 3.2 Google Calendar Real-Time Sync
**New file:** `skills/google_calendar.py`
**Dependencies:** `pip install google-api-python-client google-auth-oauthlib`

```python
class GoogleCalendarSkill(BaseSkill):
    name = "google_calendar"
    # Reads events for today/this week
    # Creates events from natural language
    # Notifies autonomy loop of upcoming meetings
    # Wires meeting alerts into _fast_tick() break reminder logic
```

Autonomy wiring in `core/autonomy.py`:
```python
async def _check_upcoming_meetings(self):
    # Query calendar 15 min before meeting
    # Trigger: "Sir, stand-up in 10 minutes. Want me to pull the agenda?"
```

### 3.3 PDF / Document Intelligence Skill
**New file:** `skills/documents.py`
**Dependencies:** `pip install pypdf2 python-docx pytesseract`

```python
class DocumentSkill(BaseSkill):
    name = "documents"
    # Actions: read_pdf, read_docx, summarize, extract_tables, ocr_image
    # Chunked reading for large PDFs (>50 pages)
    # Stores summaries in vector memory for later recall
```

### 3.4 Spotify Web API Integration
**File:** `skills/music.py` (upgrade existing)
**Dependencies:** `pip install spotipy`
**Add to .env:** `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`

```python
class MusicSkill(BaseSkill):
    # Actions: play, pause, skip, volume, current_track, search, recommend
    # Queue management, playlist creation
    # "Play something like what I was listening to on Tuesday"
```

### 3.5 Smart Email Summarizer (upgrade existing)
**File:** `skills/email_skill.py` — add to existing EmailSkill

```python
async def _summarize_inbox(self, emails: list) -> str:
    # Output: "Sir, you have 12 unread emails. 3 are urgent:
    #   1. From [name]: [one-line summary]
    #   2. Invoice from [vendor] for $X
    #   3. Meeting request from [name] for tomorrow"
    prompt = f"Summarize these emails in JARVIS briefing style: {emails[:10]}"
    return await self._assistant._router.chat(
        [{"role": "user", "content": prompt}],
        system="You are JARVIS. Be concise and flag urgent items."
    )
```

---

## Section 4: Phase 2 — Intelligence Upgrade (62% → 74%)
**Timeline: 2-3 weeks | Focus: Make JARVIS think, not just respond**

### 4.1 Self-Correcting Reasoning (ReAct Loop)
**New file:** `core/reasoning.py`

```python
class ReActEngine:
    """
    Thought -> Action -> Observation -> Thought -> Action -> ...
    Max 5 iterations before returning best answer.
    Used for complex multi-step tasks: "Book me a meeting next Tuesday"
    """
    async def solve(self, goal: str, tools: dict) -> str:
        history = []
        for step in range(5):
            thought = await self._think(goal, history)
            if thought.startswith("FINAL:"):
                return thought[6:].strip()
            action = await self._pick_action(thought, tools)
            observation = await tools[action.name](**action.args)
            history.append({"thought": thought, "action": action, "obs": observation})
        return await self._summarize(history)
```

Wire into `assistant.py`:
```python
# For complex queries (detected by intent classifier):
if self._is_complex_task(user_input):
    reply = await self.reasoning.solve(user_input, self._skill_registry)
```

### 4.2 Parallel Multi-Agent Execution
**New file:** `core/agents.py`

```python
class AgentOrchestrator:
    """
    Splits complex tasks into parallel sub-agents.
    "What is the weather, news, and my calendar for today?"
    -> Agent A: weather, Agent B: news, Agent C: calendar
    -> Merge results into single coherent JARVIS briefing
    """
    async def morning_briefing(self) -> str:
        tasks = [
            AgentTask("weather", {"location": "auto"}),
            AgentTask("news", {"category": "top"}),
            AgentTask("calendar", {"range": "today"}),
            AgentTask("finance", {"watchlist": True}),
        ]
        results = await asyncio.gather(*[self._run_task(t) for t in tasks])
        return await self._merge_briefing(results)
```

### 4.3 Deep Episodic Memory
**New file:** `core/episodic_memory.py`

```python
class EpisodicMemory:
    """
    Records and recalls full sessions with context metadata.
    JARVIS behavior: "Last Thursday when you were in VSCode, you asked about X"
    Each episode: session_id, start_time, end_time, app_context, topics[], summary
    Stored in SQLite with FTS5 full-text search
    Weekly auto-summary: "This week you primarily worked on [project]"
    """
    async def record_session(self, messages: list, ambient_snapshots: list): ...
    async def recall_relevant(self, query: str, days_back: int = 30) -> list: ...
```

### 4.4 Automatic Code Debug Loop
**File:** `skills/code_runner.py` (major upgrade)

```python
async def debug_loop(self, code: str, language: str, max_attempts: int = 3) -> dict:
    """Write -> Execute -> If error -> Fix -> Re-execute -> Repeat"""
    for attempt in range(max_attempts):
        result = await self._execute(code, language)
        if result["success"]:
            return {"code": code, "output": result["output"], "attempts": attempt + 1}
        fix_prompt = f"Fix this {language} error:\nCode:\n{code}\nError:\n{result['error']}"
        code = await self._router.chat(
            [{"role": "user", "content": fix_prompt}],
            system="Output only the fixed code, no explanation."
        )
    return {"code": code, "output": "Max attempts reached", "attempts": max_attempts}
```

### 4.5 Dynamic User Model Evolution
**File:** `core/intelligence.py` (upgrade)

```python
def evolve_model(self, new_evidence: dict):
    # Topics asked -> boost interest weights
    # Time of day patterns -> schedule awareness
    # Tone/urgency -> emotional state model
    # Repeated questions -> knowledge gap detection
    self._user_model.update_interests(new_evidence["topics"])
    self._user_model.update_schedule(new_evidence["timestamp"])
    self._user_model.detect_knowledge_gaps(new_evidence["questions"])
```

---

## Section 5: Phase 3 — Sensory & Physical (74% → 83%)
**Timeline: 3-4 weeks | Focus: Give JARVIS eyes and hands**

### 5.1 Webcam Presence Detection
**New file:** `core/presence.py`
**Dependencies:** `pip install opencv-python mediapipe`

```python
class PresenceDetector:
    """
    Uses webcam to detect if user is at desk.
    - User sits down -> "Good morning, Sir. Ready to begin?"
    - User walks away -> pause autonomy, save state
    - User returns -> "Welcome back. You were working on [X]."
    Background thread, 2fps, 120-second away threshold
    """
    def start(self): ...        # background thread
    def is_present(self) -> bool: ...
    def on_arrive(self, callback): ...  # hook for autonomy engine
    def on_depart(self, callback): ...
```

### 5.2 Screen OCR Reader
**New file:** `skills/screen_reader.py`
**Dependencies:** `pip install pytesseract Pillow mss`

```python
class ScreenReaderSkill(BaseSkill):
    name = "screen_reader"
    # "What does that error say?" -> captures screen, OCRs, returns text
    # "Read the article I am looking at" -> OCR browser window region
    # Stores screen text in short-term memory for follow-up questions
    # Actions: read_screen, read_region, find_text, screenshot
```

### 5.3 Complete System Controls
**File:** `skills/system_control.py` (major upgrade)

```python
# Add beyond current volume/brightness:
# - App launcher: "Open Spotify"
# - File opener: "Open my resume"
# - Window manager: "Move this to second monitor"
# - Clipboard manager: "What did I copy last?"
# - Process manager: "What is using my CPU?"
# - Screen lock/sleep: "Lock the computer"
# - Network: "Check my ping", "Switch to WiFi X"
```

### 5.4 WhatsApp Integration
**New file:** `skills/whatsapp.py`
**Via:** Twilio WhatsApp API

```python
class WhatsAppSkill(BaseSkill):
    name = "whatsapp"
    # Read incoming messages, send to contacts
    # "Message Pepper that I will be late"
    # Group messages + media support
```

### 5.5 Health & Fitness Tracking
**New file:** `skills/health.py`
**Via:** Google Fit API + manual logging

```python
class HealthSkill(BaseSkill):
    name = "health"
    # Log: steps, water, sleep, exercise, calories
    # "Sir, you have not logged water in 3 hours"
    # Weekly/monthly trends
    # Integration with break reminders in autonomy.py
```

---

## Section 6: Phase 4 — Interface & Presence (83% → 90%)
**Timeline: 4-6 weeks | Focus: JARVIS feels real, not just functional**

### 6.1 Electron Desktop App (Always-On HUD)
**New directory:** `desktop/`

```
desktop/
+-- main.js       # Electron main process
+-- preload.js    # Context bridge for IPC
+-- renderer/     # Reuse frontend/index.html assets
+-- tray.js       # System tray icon + quick actions
+-- package.json
```

Key features:
- Frameless, always-on-top transparent overlay
- System tray icon, hotkey `Alt+J` to show/hide
- Corner HUD widget showing live vitals only
- Native OS notifications via Electron Notification API
- Auto-start with Windows/Mac at login

### 6.2 Progressive Web App (PWA Mobile)
**New files:** `frontend/manifest.json` + `frontend/sw.js`

Mobile-specific UI:
- Bottom navigation bar (Chat, Status, Skills, Settings)
- Large touch-friendly buttons
- Voice-first interface on mobile
- Push notifications for autonomy events
- Works offline for viewing history

### 6.3 Live HUD Dashboard Panels
New panels to add to `frontend/index.html`:
- Memory timeline — scrollable episodic memory visualizer
- Live skill activity graph — which skills fired today/this session
- User model display — real-time interest weights radar chart
- Conversation sentiment tracker — mood over time
- Autonomy event log — scrollable real-time event feed

### 6.4 Custom Voice Model
**New file:** `voice/custom_tts.py`

Options in order of quality:
1. **ElevenLabs API** (best): JARVIS-style British voice, or clone any voice from 60s sample
2. **Coqui TTS local** (free, private): fine-tune on JARVIS speech samples, ~2s on CPU
3. **edge-tts**: stays as fallback (current)

```python
# voice/custom_tts.py
class CustomTTS:
    async def synthesize(self, text: str) -> bytes:
        # Try ElevenLabs first, fall back to Coqui, then edge-tts
        ...
```

---

## Section 7: Phase 5 — The Final 10% (90% → 95%)
**Timeline: 6-10 weeks | Focus: What makes JARVIS feel alive**

### 7.1 Intent Router v2 (Zero-Shot Classification)
**New file:** `core/intent.py`

Routes user input to skill BEFORE LLM call — saves 200-400ms per message for common intents.

```python
class IntentRouter:
    INTENTS = {
        "weather": ["weather", "temperature", "rain", "forecast", "humidity"],
        "email": ["email", "mail", "inbox", "send", "reply", "unread"],
        "calendar": ["meeting", "schedule", "appointment", "remind", "when is"],
        "music": ["play", "pause", "skip", "volume", "song", "track"],
        "system": ["open", "close", "volume", "brightness", "lock", "shutdown"],
    }

    def classify(self, text: str) -> tuple[str, float]:
        # 1. Fast keyword matching (<1ms)
        # 2. Fall back to lightweight embedding classifier
        # Returns: (intent_name, confidence_score)
```

### 7.2 Relationship Model
**New file:** `core/relationships.py`

```python
class RelationshipModel:
    """
    Knows who people in the user's life are.
    "Message Pepper" -> resolves to Pepper's phone/email
    "When is Dad's birthday?" -> knows family dates
    """
    # SQLite: name, relationship_type, contact_info, notes, important_dates
    # Populated from: Gmail contacts scan + manually told facts
    # JARVIS behavior: "Should I add this to your contacts, Sir?"
```

### 7.3 Overnight Research Agent
**New file:** `core/overnight_agent.py`

```python
class OvernightAgent:
    """Runs deep research tasks while user sleeps (midnight-5am)."""

    async def run_research(self, topic: str, depth: int = 3) -> str:
        # Step 1: Web search for recent developments (SerpAPI)
        # Step 2: Summarize top 10 sources via LLM
        # Step 3: Extract key facts + contradictions
        # Step 4: Generate structured report
        # Step 5: Store in vector memory + email summary at wake-up

    async def schedule_overnight(self, tasks: list[str]):
        # Called by autonomy slow_tick when tasks queued
        # Checks: is it after 11pm? Is user idle?
```

### 7.4 Transparency Layer
**New file:** `core/transparency.py`

```python
class TransparencyEngine:
    """JARVIS always tells you what it is doing and why."""
    # "Searching the web because I do not have current data on X"
    # "Using Groq because Cerebras circuit breaker is open"
    # "Recalled 3 memories from last Tuesday relevant to this"
    def explain_action(self, action: str, reason: str) -> str: ...
    def explain_routing(self, provider: str, why: str) -> str: ...
    def explain_memory_hit(self, memories: list) -> str: ...
```

### 7.5 3D Particle HUD
**Frontend upgrade using Three.js**

```javascript
// Replace SVG waveform with Three.js particle system
// 2000 particles that react to: voice activity, CPU load, AI thinking state
// Thinking: particles converge to center sphere
// Speaking: particles explode outward in sync with audio amplitude
// Idle: gentle orbital drift with occasional spark bursts
// Typing: particles ripple from keyboard position
import * as THREE from 'three';
const particleCount = 2000;
```

---

## Section 8: Master Technology Stack

### Current (Working)
```
Backend:    Python 3.11, FastAPI, asyncio, uvicorn
LLM:        Groq (llama-3.3-70b) -> Cerebras -> OpenAI -> Gemini x3 -> Ollama
Memory:     ChromaDB (vector) + SQLite (long-term) + ring buffer (short-term)
Voice:      Whisper (local STT) + edge-tts (TTS) + Porcupine (wake word)
Frontend:   Vanilla HTML/CSS/JS, WebSocket streaming
Storage:    Local filesystem + Supabase (cloud sync)
Skills:     19 registered skills
```

### Phase 1 Additions
```
google-api-python-client    -> Google Calendar
google-auth-oauthlib        -> OAuth for Calendar
pypdf2, python-docx         -> Document reading
pytesseract                 -> OCR
spotipy                     -> Spotify Web API
```

### Phase 2 Additions
```
sqlite3 FTS5 (built-in)     -> Episodic memory full-text search
asyncio.gather (built-in)   -> Parallel agents (no new dep)
```

### Phase 3 Additions
```
opencv-python               -> Presence detection
mediapipe                   -> Face detection
mss                         -> Screen capture
twilio                      -> WhatsApp
google-api-python-client    -> Google Fit
```

### Phase 4 Additions
```
electron + nodejs           -> Desktop app
elevenlabs or coqui-tts     -> Custom voice
workbox                     -> PWA service worker
```

### Phase 5 Additions
```
three.js                    -> 3D particle HUD
sentence-transformers       -> Local intent classification (optional)
```

---

## Section 9: Complete File Structure

### New Files to Create
```
core/
+-- reasoning.py            # ReAct self-correcting loop
+-- agents.py               # Parallel multi-agent orchestrator
+-- episodic_memory.py      # Session-level memory with SQLite FTS5
+-- presence.py             # Webcam presence detection
+-- intent.py               # Zero-shot intent router
+-- relationships.py        # Contact/relationship model
+-- overnight_agent.py      # Autonomous overnight research
+-- transparency.py         # Explain-my-actions layer

skills/
+-- google_calendar.py      # Real Google Calendar (OAuth)
+-- documents.py            # PDF/Word/OCR reader
+-- screen_reader.py        # Live screen OCR
+-- whatsapp.py             # WhatsApp via Twilio
+-- health.py               # Fitness/health tracking

desktop/
+-- main.js                 # Electron main process
+-- preload.js              # IPC bridge
+-- tray.js                 # System tray
+-- package.json

voice/
+-- custom_tts.py           # ElevenLabs / Coqui TTS wrapper

frontend/
+-- manifest.json           # PWA manifest
+-- sw.js                   # Service worker for offline support
```

### Files to Upgrade
```
core/assistant.py           # Wire: reasoning, agents, episodic memory, transparency
core/autonomy.py            # Wire: calendar alerts, presence hooks, overnight agent
core/intelligence.py        # Add: dynamic user model evolution
skills/code_runner.py       # Add: auto debug loop
skills/email_skill.py       # Add: smart inbox summarizer
skills/music.py             # Add: Spotify Web API full control
skills/system_control.py    # Add: app launcher, clipboard, window manager
server/app.py               # Add: /ws/gemini-live, /api/memory/episodes
frontend/index.html         # Add: new HUD panels, PWA meta tags, Three.js
.env                        # Add: SPOTIFY_CLIENT_ID/SECRET, ELEVENLABS_API_KEY
core/config.py              # Add: config fields for all new integrations
```

---

## Section 10: Priority Matrix

### Impact vs Effort Grid

| Feature | Impact | Effort | Phase | Score Jump |
|---------|--------|--------|-------|------------|
| Gemini Live activation | HIGH | LOW | 1 | +3% |
| Smart email summarizer | HIGH | LOW | 1 | +2% |
| Google Calendar sync | HIGH | MEDIUM | 1 | +4% |
| PDF/Document skill | HIGH | MEDIUM | 1 | +3% |
| Parallel multi-agent | HIGH | MEDIUM | 2 | +4% |
| ReAct reasoning loop | HIGH | HIGH | 2 | +4% |
| Episodic memory | MEDIUM | MEDIUM | 2 | +3% |
| Intent router v2 | HIGH | LOW | 5 | +2% |
| Spotify Web API | MEDIUM | LOW | 1 | +2% |
| Webcam presence | HIGH | MEDIUM | 3 | +3% |
| Screen OCR | HIGH | LOW | 3 | +3% |
| Electron desktop app | HIGH | HIGH | 4 | +4% |
| Custom voice model | MEDIUM | HIGH | 4 | +3% |
| Relationship model | HIGH | MEDIUM | 5 | +2% |
| Overnight research | MEDIUM | MEDIUM | 5 | +2% |
| WhatsApp | MEDIUM | MEDIUM | 3 | +2% |
| 3D particle HUD | LOW | HIGH | 5 | +1% |
| Health tracking | LOW | MEDIUM | 3 | +2% |
| Transparency layer | MEDIUM | LOW | 5 | +1% |
| PWA mobile | MEDIUM | HIGH | 4 | +3% |

### Score Projections
```
Today (2026-05-07):  47/100  <- Current state
After Phase 1:       62/100  <- Foundation complete
After Phase 2:       74/100  <- Intelligence upgrade
After Phase 3:       83/100  <- Sensory + physical
After Phase 4:       90/100  <- Interface + presence
After Phase 5:       95/100  <- Final polish
```

### Recommended Build Order (Quick Wins First)
1. Smart email summarizer (2 hours, +2%)
2. Intent router v2 (4 hours, +2%, speeds up every query)
3. Gemini Live activation (4 hours, +3%)
4. Spotify Web API (6 hours, +2%)
5. Screen OCR skill (6 hours, +3%)
6. Google Calendar sync (8 hours, +4%)
7. PDF/Document skill (8 hours, +3%)
8. Episodic memory (12 hours, +3%)
9. Parallel multi-agent (12 hours, +4%)
10. ReAct reasoning loop (16 hours, +4%)

---

## Section 11: What 100% Would Actually Require

Honest assessment of the final 5% gap (95 → 100):

### Hardware Requirements
- Custom silicon ASICs: Tony's JARVIS runs on dedicated chips, not consumer GPUs
- Dedicated server room: millisecond-latency over private high-speed network
- Always-on wearable: biometric data from suit sensors (heart rate, location, vitals)

### Data Requirements
- Years of continuous interaction data: JARVIS has been learning Tony for years
- Complete life digitization: every email, calendar, note, purchase, health record
- Real-time financial data feeds: Bloomberg Terminal level, not free API tiers

### AI Capability Requirements
- Multimodal spatial awareness: JARVIS sees the workshop in 3D, not just text/screen
- Persistent real-world model: continuous model of Tony's physical + digital environment
- True task autonomy: orders parts, makes calls, runs experiments without being asked
- Emotional intelligence: detects stress/mood from voice acoustics + biometrics

### Infrastructure Requirements
- Private cloud: no rate limits, no shared infrastructure, no latency variance
- Sub-100ms global latency: requires edge deployment across multiple regions
- 99.999% uptime: JARVIS never goes down, even when Stark Tower loses power

### The Honest Ceiling
A personal Javris running on one computer with free/cheap APIs will realistically reach
**85-90% of the functional behavior** of JARVIS. The remaining gap:

- Response latency: our 200-500ms vs JARVIS apparent sub-50ms
- Depth of world model: we know what we are told; JARVIS knows everything
- Physical autonomy: we cannot order parts or control physical hardware
- Always-on presence: Javris is dormant when the server is off

**But 85-90% of Iron Man's JARVIS is still extraordinary.** The plan above will take you there.

---

## Quick-Start: Next Steps This Week

```bash
# Day 1: Quick wins (no new dependencies)
# 1. Add _summarize_inbox() to skills/email_skill.py
# 2. Create core/intent.py with keyword intent router
# 3. Wire Gemini Live into server/app.py WebSocket endpoint

# Day 2-3: Calendar
pip install google-api-python-client google-auth-oauthlib
# Create skills/google_calendar.py
# Wire _check_upcoming_meetings() into core/autonomy.py _fast_tick()

# Day 4-5: Documents + Screen OCR
pip install pypdf2 python-docx pytesseract pillow mss
# Create skills/documents.py
# Create skills/screen_reader.py

# Day 6-7: Music upgrade
pip install spotipy
# Upgrade skills/music.py with Spotify play/pause/search
# Add to .env: SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...
```

---

*"The truth is, I am Iron Man." — Tony Stark*
*The truth is, this plan will make you damn close.*

**Generated by Claude Code | Javris Project | 2026-05-07**

---

# Advanced Architecture Addendum - Codex Implementation Plan
**Date:** 2026-05-08  
**Purpose:** Convert Javris from a feature-rich assistant into a secure, observable, fault-tolerant, event-driven personal intelligence operating system.

This addendum does not replace the existing plan. It adds the missing production-grade architecture: security, permissions, failure handling, autonomous task execution, observability, memory governance, fallback logic, test strategy, and a highly structured long-term system design.

---

## Section 12: Immediate Reality Check

The current project already has useful foundations:

- Multi-provider LLM router
- FastAPI backend and WebSocket dashboard
- Skill registry
- Memory stack: short-term, SQLite, vector memory
- Autonomy loop
- Voice, computer-use, gesture, storage, and HUD components

However, the project is not yet ready to behave like a deeply reliable personal AI system because several foundational issues must be solved before adding more features.

### Critical issues to fix first

| Priority | Area | Current Risk | Required Fix |
|---------|------|--------------|--------------|
| P0 | Secrets | Email credentials and API keys can leak | Remove hardcoded secrets, rotate leaked credentials, use secret manager |
| P0 | API Security | Powerful endpoints are unauthenticated | Add auth, local tokens, permissions, CSRF protection |
| P0 | Autonomy | Morning digest calls removed `_call_llm` path | Replace with router-based LLM calls |
| P0 | Tool Safety | Code runner executes with full user permissions | Sandbox code execution |
| P0 | Browser Control | Computer agent can act without strict policy | Add human approval gates for sensitive actions |
| P1 | Router Logic | Hedging cancels useful providers too early | Keep pending hedged provider alive after first failure |
| P1 | Frontend/API Drift | HUD reads `cpu` and `memory`, API returns `cpu_percent` and `ram_percent` | Align response contract |
| P1 | Observability | No full trace of autonomous decisions | Add event ledger, traces, metrics |
| P1 | Skill Reliability | Skill calls have inconsistent errors | Standardize skill result schema |
| P2 | Memory Quality | Vector memory stores raw turns without summarization hierarchy | Add episodic, semantic, preference, and relationship layers |

---

## Section 13: Target Architecture - Javris Personal Intelligence OS

The final architecture should be layered, event-driven, permissioned, and observable.

```text
Interface Layer
  - Web HUD
  - CLI
  - Voice mode
  - Mobile PWA
  - Desktop overlay
  - Gesture control

API Gateway Layer
  - FastAPI
  - Authentication
  - Rate limits
  - Request IDs
  - User/session context
  - CSRF and origin checks

Event Layer
  - Typed event bus
  - Durable event ledger
  - WebSocket fanout
  - Audit trail
  - Replay/debug tooling

Orchestration Layer
  - Assistant core
  - Intent router
  - Planner
  - Agent orchestrator
  - Task manager
  - Context broker

Cognition Layer
  - LLM router
  - Reasoning engine
  - Reflection engine
  - Critic/verifier
  - Tool-use policy engine
  - Evaluation harness

Memory Layer
  - Working memory
  - Episodic memory
  - Semantic memory
  - Preference memory
  - Relationship graph
  - Project memory
  - Memory compaction and decay

Capability Layer
  - Skills
  - Computer/browser agent
  - Voice engine
  - Vision/screen OCR
  - Documents
  - Calendar/email/music/files/system

Autonomy Layer
  - Schedules
  - Triggers
  - Presence detection
  - Self-healing jobs
  - Overnight research
  - Proactive briefings

Safety Layer
  - Permission engine
  - Confirmation gates
  - Data-loss prevention
  - Secret isolation
  - Code sandbox
  - Prompt-injection firewall

Infrastructure Layer
  - SQLite/Postgres
  - Chroma/Qdrant
  - Object storage
  - Local encrypted secret store
  - Logs, metrics, traces
  - Backup and restore
```

---

## Section 14: P0 Stabilization Plan - Fix The Core Before Expanding

### 14.1 Secret and Credential Hardening

**Problem:** Hardcoded secrets make the assistant unsafe. A real personal assistant has access to email, files, browser sessions, messages, and eventually payments or smart-home systems. Secret leakage is catastrophic.

**Implementation:**

```text
New files:
core/secrets.py
core/security/redaction.py
scripts/rotate_secrets_check.py

Upgrade:
core/config.py
skills/email_skill.py
server/app.py
.env.example
```

**Rules:**

- No default real credentials in source code.
- `.env` may be used for local development only.
- Runtime secrets should be pulled through `SecretProvider`.
- Logs must redact tokens, passwords, app passwords, cookies, API keys, bearer tokens, and email auth strings.
- Startup should refuse to run in production mode if `JAVRIS_SECRET_KEY=change_me`.

**SecretProvider design:**

```python
class SecretProvider:
    async def get(self, name: str) -> str: ...
    async def set(self, name: str, value: str) -> None: ...
    async def rotate_required(self, name: str) -> bool: ...
    def redact(self, text: str) -> str: ...
```

**Acceptance criteria:**

- `rg "password|app_password|api_key|token"` shows no real secret values.
- Logs never display full secrets.
- Email skill returns a clear setup error when credentials are missing.
- A script verifies secret hygiene before commit.

### 14.2 API Authentication and Authorization

**Problem:** Localhost APIs are still dangerous. Browser pages, extensions, malware, or local network clients can hit endpoints if the server binds to `0.0.0.0`.

**Implementation:**

```text
New files:
core/security/auth.py
core/security/permissions.py
core/security/policies.py
core/security/sessions.py

Upgrade:
server/app.py
frontend/index.html
core/config.py
```

**Required controls:**

- Bearer token for API calls.
- WebSocket auth token during connection.
- Optional local-only mode binding to `127.0.0.1`.
- Strict CORS allowlist.
- CSRF token for browser-origin requests.
- Admin-only routes for API key changes and LLM circuit resets.

**Permission classes:**

```text
READ_PUBLIC          - weather, news, basic search
READ_PRIVATE         - email read, files read, calendar read, memory read
WRITE_PRIVATE        - notes, calendar create, file write
SEND_EXTERNAL        - email, telegram, discord, whatsapp
CONTROL_COMPUTER     - browser control, OS control, gestures
EXECUTE_CODE         - code runner
DELETE_OR_DESTRUCTIVE - delete files, delete emails, close apps
FINANCIAL_OR_PURCHASE - trading, orders, subscriptions, purchases
```

**Policy behavior:**

- Low-risk actions can run silently.
- Medium-risk actions require first-time approval.
- High-risk actions require approval every time.
- Destructive or external-send actions show a review screen.
- Policy decisions are written to the audit ledger.

### 14.3 Standard Skill Result Contract

**Problem:** Skills return strings, lists, dicts, and inconsistent error formats. This makes planning, recovery, frontend display, and testing harder.

**New schema:**

```python
class SkillResult(BaseModel):
    ok: bool
    skill: str
    action: str
    data: dict = {}
    summary: str = ""
    error: str = ""
    error_type: str = ""
    retryable: bool = False
    confidence: float = 1.0
    requires_confirmation: bool = False
    audit: dict = {}
```

**Upgrade all skills gradually:**

- Email
- Weather
- News
- Finance
- Music
- System control
- Notes
- Browser
- Code runner
- Calendar
- GitHub
- Notion
- Obsidian

### 14.4 Router Hedging and Fallback Correctness

**Problem:** The router should not cancel a slower provider if the first completed provider fails. It should only cancel losers once a valid success arrives.

**Fix strategy:**

- Launch top two providers.
- If one succeeds, cancel the other.
- If one fails, keep the other running.
- If both fail, try remaining providers sequentially.
- Track error classes: timeout, rate limit, auth failure, model failure, malformed response.
- Surface routing trace to `/api/llm/health`.

**Router trace example:**

```json
{
  "request_id": "req_123",
  "strategy": "hedged",
  "attempts": [
    {"provider": "groq", "status": "failed", "error_type": "rate_limit"},
    {"provider": "cerebras", "status": "success", "latency_ms": 420}
  ],
  "winner": "cerebras"
}
```

### 14.5 Code Runner Isolation

**Problem:** The current code runner executes Python directly. That is not a secure sandbox.

**Implementation layers:**

1. Minimal local mode:
   - Temporary isolated directory
   - Timeout
   - No inherited secrets in env
   - Limited stdout/stderr
   - Explicit disabled network warning

2. Strong mode:
   - Docker container
   - Readonly root filesystem
   - Memory and CPU limits
   - Network disabled by default
   - Mounted scratch directory only

3. Advanced mode:
   - Firecracker/microVM or Windows Sandbox profile
   - Policy-selected runtime
   - Per-run artifact capture

**Never allow:**

- Direct access to `.env`
- Arbitrary filesystem writes outside scratch
- Shell commands without permission classification
- Long-running background processes

---

## Section 15: Event Bus and Durable Task Ledger

### 15.1 Typed Event Bus

**Problem:** Components call each other directly. This creates fragile coupling.

**New file:** `core/events.py`

```python
class Event(BaseModel):
    event_id: str
    type: str
    source: str
    timestamp: float
    priority: str = "low"
    correlation_id: str = ""
    payload: dict = {}

class EventBus:
    async def publish(self, event: Event) -> None: ...
    def subscribe(self, event_type: str, handler: Callable) -> None: ...
    async def replay(self, since: float) -> list[Event]: ...
```

**Event categories:**

- `chat.message.received`
- `chat.response.started`
- `chat.response.chunk`
- `chat.response.completed`
- `tool.call.started`
- `tool.call.completed`
- `tool.call.failed`
- `memory.write`
- `memory.recall`
- `autonomy.triggered`
- `policy.approval.required`
- `policy.approval.granted`
- `computer.action.started`
- `computer.action.completed`
- `llm.route.selected`
- `llm.provider.failed`

### 15.2 Durable Task Ledger

**Problem:** Autonomous work needs persistence and forensic traceability.

**New files:**

```text
core/tasks.py
core/task_store.py
data/migrations/001_task_ledger.sql
```

**Tables:**

```sql
tasks(
  task_id TEXT PRIMARY KEY,
  goal TEXT,
  status TEXT,
  risk_level TEXT,
  created_at REAL,
  updated_at REAL,
  completed_at REAL,
  owner TEXT,
  result_summary TEXT,
  error TEXT
)

task_steps(
  step_id TEXT PRIMARY KEY,
  task_id TEXT,
  step_index INTEGER,
  action_type TEXT,
  tool_name TEXT,
  input_json TEXT,
  output_json TEXT,
  status TEXT,
  started_at REAL,
  ended_at REAL,
  error TEXT
)

audit_events(
  event_id TEXT PRIMARY KEY,
  correlation_id TEXT,
  actor TEXT,
  action TEXT,
  resource TEXT,
  decision TEXT,
  reason TEXT,
  timestamp REAL,
  payload_json TEXT
)
```

**Every autonomous action must answer:**

- What was the goal?
- What did Javris know at that time?
- Which model/provider made the decision?
- Which tool was called?
- What was the result?
- Was user approval required?
- What fallback happened after failure?

---

## Section 16: Context Broker - The Brain's Input Firewall

### 16.1 Why This Matters

A sophisticated assistant fails if it gives the LLM too much context, wrong context, stale context, or unsafe context. The context broker decides what information enters each model call.

**New file:** `core/context_broker.py`

```python
class ContextBroker:
    async def build_context(
        self,
        user_input: str,
        task_type: str,
        budget_tokens: int,
        risk_level: str,
    ) -> ContextBundle: ...
```

### 16.2 Context Sources

```text
Conversation memory
Episodic memory
User preferences
Relationship graph
Current app/window
Screen OCR
Calendar
Recent files
Active tasks
Skill results
System vitals
Location/weather
Current time
Project-specific memory
```

### 16.3 Context Ranking

Each candidate context item gets:

```text
relevance_score
recency_score
trust_score
sensitivity_score
token_cost
source_type
expiration_time
```

The broker should select the highest-value context within a token budget and block untrusted prompt-injection content from directly becoming system instructions.

### 16.4 Prompt Injection Firewall

Documents, webpages, emails, OCR text, and browser pages are untrusted input.

**Rules:**

- Untrusted text must be quoted as data, never instructions.
- Tool calls suggested by untrusted text require policy review.
- Webpages cannot override system/developer instructions.
- Emails cannot instruct Javris to send files, reveal secrets, or execute code.
- Browser agent must separate page content from control instructions.

---

## Section 17: Advanced Memory Architecture

### 17.1 Memory Types

```text
Working Memory
  - Last few turns
  - Active task state
  - Current screen/app context

Episodic Memory
  - Sessions
  - Daily summaries
  - Project timelines
  - "What happened last Thursday?"

Semantic Memory
  - Facts
  - Concepts
  - User-learned knowledge
  - Documents and notes

Preference Memory
  - Style
  - Habits
  - Preferred tools
  - Repeated corrections

Relationship Memory
  - People
  - Contact methods
  - Importance
  - Boundaries
  - Events and birthdays

Procedural Memory
  - Reusable workflows
  - "How I usually do X"
  - Automation recipes
```

### 17.2 New Modules

```text
core/memory_layers/
  working.py
  episodic.py
  semantic.py
  preferences.py
  relationships.py
  procedural.py
  compaction.py
  retrieval.py
```

### 17.3 Memory Compaction Pipeline

Every conversation should be distilled:

```text
Raw turns -> session summary -> facts -> preferences -> project updates -> embeddings
```

**Daily job:**

- Summarize all sessions for the day.
- Extract durable facts.
- Detect changed preferences.
- Update relationship graph.
- Generate "what changed today" digest.

**Weekly job:**

- Merge duplicate facts.
- Decay stale assumptions.
- Ask user to confirm uncertain facts.
- Archive low-value memory.

### 17.4 Memory Confidence

Every memory item should carry:

```text
confidence: 0.0-1.0
source: user/direct/inferred/imported
last_confirmed_at
expires_at
contradicted_by
sensitivity
```

Javris should say "I think" when memory confidence is low and ask for confirmation before using uncertain personal details.

---

## Section 18: Planner, Reasoning, Critic, and Execution

### 18.1 Planner

**New file:** `core/planner.py`

The planner turns broad goals into executable steps.

```python
class Planner:
    async def plan(self, goal: str, context: ContextBundle) -> Plan: ...
```

**Plan schema:**

```python
class PlanStep(BaseModel):
    step_id: str
    description: str
    tool: str | None
    inputs: dict
    risk_level: str
    requires_confirmation: bool
    fallback: str
```

### 18.2 Execution Engine

**New file:** `core/executor.py`

```python
class Executor:
    async def execute(self, plan: Plan) -> ExecutionResult:
        for step in plan.steps:
            await policy.check(step)
            result = await tools.run(step)
            await verifier.verify(step, result)
            if result.failed:
                await recovery.recover(step, result)
```

### 18.3 Critic and Verifier

**New file:** `core/verifier.py`

The verifier checks whether the result actually satisfies the step.

Examples:

- If email was sent, verify SMTP success and recipient.
- If calendar event was created, read it back.
- If file was modified, compare before/after.
- If browser clicked submit, verify page state changed.
- If LLM gave answer, check citations or calculations for high-risk domains.

### 18.4 Recovery Engine

**New file:** `core/recovery.py`

Failure classes:

```text
TRANSIENT_NETWORK
RATE_LIMIT
AUTH_EXPIRED
BAD_INPUT
TOOL_BUG
POLICY_BLOCKED
MODEL_REFUSAL
LOW_CONFIDENCE
STATE_MISMATCH
UNKNOWN
```

Recovery policy:

```text
rate_limit -> switch provider or wait
auth_expired -> ask user to reconnect
bad_input -> ask clarifying question
tool_bug -> retry once, then log bug
state_mismatch -> re-observe environment
policy_blocked -> ask for approval or refuse
unknown -> stop safely and preserve trace
```

---

## Section 19: Autonomy 2.0

### 19.1 Autonomy Should Be Event Driven

Current autonomy uses ticks. Keep ticks for periodic checks, but add event-driven triggers.

**Triggers:**

```text
user_arrived
user_left
calendar_event_soon
email_urgent
system_resource_high
download_completed
file_changed
browser_task_failed
new_memory_conflict
daily_shutdown
morning_start
```

### 19.2 Autonomy Levels

```text
Level 0: Passive only
  - Responds when asked

Level 1: Notify
  - Alerts user but takes no action

Level 2: Prepare
  - Drafts, summarizes, queues actions

Level 3: Act with approval
  - Performs actions after confirmation

Level 4: Trusted autonomous
  - Performs approved routine actions

Level 5: Restricted forbidden zone
  - Never act without explicit approval: money, deletion, external sending, credentials
```

### 19.3 Self-Healing Loop

**New file:** `core/self_healing.py`

Every 10 minutes:

- Check LLM providers.
- Check skill health.
- Check database connectivity.
- Check vector memory health.
- Check browser agent state.
- Check disk and temp folders.
- Run minimal smoke tests.
- Open/close circuits.
- Emit dashboard warnings.

### 19.4 Overnight Agent

Upgrade the existing research idea into a job queue:

```text
Input queue:
  - research topics
  - documents to summarize
  - inbox cleanup
  - memory compaction
  - skill health checks
  - project codebase scans

Output:
  - morning report
  - action suggestions
  - saved memory summaries
  - tasks needing approval
```

---

## Section 20: Computer-Use Agent Hardening

### 20.1 Current Risk

The browser agent can click, type, navigate, submit forms, and answer quizzes. This is powerful but risky.

### 20.2 Required Safety Gates

Before any action:

```text
Classify action risk
Check domain allowlist/blocklist
Check whether page contains payment, auth, medical, legal, financial, or destructive actions
Require confirmation when needed
Log screenshot hash and action
Verify result after action
```

### 20.3 Browser Agent Architecture

```text
Observe
  - Screenshot
  - DOM snapshot
  - Accessibility tree
  - URL/title
  - Visible text

Interpret
  - Summarize state
  - Detect forms/buttons
  - Detect sensitive fields

Plan
  - Choose one atomic action
  - Predict expected result

Policy Check
  - Allow/deny/confirm

Act
  - Execute with Playwright

Verify
  - Re-observe
  - Compare expected vs actual

Record
  - Task ledger
  - Screenshots if allowed
  - Error/fallback
```

### 20.4 Sensitive Page Detection

Detect and gate:

- Password fields
- Payment forms
- Banking pages
- Trading pages
- Healthcare pages
- Government forms
- Delete/account closure buttons
- Send/submit/post/publish actions
- File upload dialogs

---

## Section 21: Skill System 2.0 - Plugin-Grade Capabilities

### 21.1 Problem

Skills are currently imported directly in assistant startup. This makes the core hard to scale.

### 21.2 Skill Manifest

Each skill should define:

```yaml
name: email
version: 1.0.0
description: Gmail skill
risk_classes:
  - READ_PRIVATE
  - SEND_EXTERNAL
config:
  required:
    - GMAIL_ADDRESS
    - GMAIL_APP_PASSWORD
actions:
  read:
    risk: READ_PRIVATE
  send:
    risk: SEND_EXTERNAL
    confirmation: always
healthcheck: true
```

### 21.3 Dynamic Loader

**New files:**

```text
core/skills/loader.py
core/skills/registry.py
core/skills/schema.py
skills/*/skill.yaml
```

The registry should support:

- Enable/disable skill
- Healthcheck
- Version
- Permissions
- Config validation
- Tool schema export
- Per-skill metrics

---

## Section 22: Observability and Debuggability

### 22.1 Request Tracing

Every user request gets:

```text
correlation_id
session_id
task_id
model/provider trace
memory retrieval trace
tool calls
policy decisions
latency breakdown
final response
```

### 22.2 Metrics

Track:

- LLM latency by provider
- LLM error rates
- Token usage
- Cost estimate
- Cache hit rate
- Skill success/failure
- Tool latency
- Autonomy event count
- Memory retrieval quality
- Browser task success rate
- Voice STT/TTS latency
- WebSocket reconnects

### 22.3 Dashboard Panels

Add panels:

- Live trace viewer
- Task ledger
- Skill health matrix
- Provider latency chart
- Memory explorer
- Permission queue
- Autonomy timeline
- Error inbox

---

## Section 23: Evaluation Harness

### 23.1 Why

You cannot improve what you cannot measure. A sophisticated assistant needs automated evaluation, not only unit tests.

### 23.2 Eval Types

```text
Intent routing evals
Memory recall evals
Tool selection evals
Permission policy evals
Prompt-injection evals
Browser task evals
Document QA evals
Voice command evals
Latency evals
Regression evals
```

### 23.3 New Structure

```text
evals/
  datasets/
    intent_cases.jsonl
    memory_cases.jsonl
    policy_cases.jsonl
    prompt_injection_cases.jsonl
    tool_cases.jsonl
  run_evals.py
  scoring.py
  reports/
```

### 23.4 Required Metrics

```text
intent_accuracy >= 95%
unsafe_action_block_rate >= 99%
memory_recall_precision >= 85%
tool_success_rate >= 90%
router_success_rate >= 99%
p95_chat_latency <= target per mode
browser_task_completion >= 80% on controlled tasks
```

---

## Section 24: Frontend and Interface Upgrade

### 24.1 Split the Single HTML File

`frontend/index.html` is too large. Split into:

```text
frontend/
  index.html
  src/
    api.js
    ws.js
    state.js
    panels/
      chat.js
      tasks.js
      memory.js
      autonomy.js
      computer.js
      settings.js
    components/
      modal.js
      toast.js
      permission_prompt.js
      trace_viewer.js
    styles/
      base.css
      panels.css
      hud.css
```

### 24.2 Permission UX

When Javris wants to do something risky:

```text
Action: Send email
To: example@example.com
Subject: ...
Risk: external communication
Reason: user asked to draft and send
Model confidence: 0.91

Buttons:
  Approve once
  Approve always for this contact
  Edit first
  Deny
```

### 24.3 Live Reasoning Visibility

Show safe summaries, not hidden chain-of-thought:

- "I am checking your calendar."
- "I found 3 relevant memories."
- "I need approval before sending this email."
- "Groq failed due to rate limit, using Cerebras."
- "The browser action did not produce the expected result, retrying with DOM selector."

---

## Section 25: Data Architecture

### 25.1 SQLite Now, Postgres Later

SQLite is fine for local-first mode. Add migrations and schema versioning now so future Postgres migration is clean.

**New files:**

```text
core/db.py
core/migrations.py
data/migrations/
```

### 25.2 Suggested Tables

```text
messages
sessions
episodes
facts
preferences
relationships
tasks
task_steps
events
audit_events
skill_runs
llm_calls
documents
document_chunks
permissions
approvals
user_feedback
```

### 25.3 Backup and Restore

Add:

- Local encrypted backups
- Export to JSON
- Restore command
- Backup healthcheck
- Redacted backup option

---

## Section 26: Failure Handling Matrix

| Failure | Detection | Fallback | User Message |
|--------|-----------|----------|--------------|
| LLM provider timeout | Router timeout | Try next provider | "Provider was slow, I switched routes." |
| Rate limit | HTTP 429 | Circuit open + fallback | "Fast provider is cooling down." |
| Bad API key | 401/403 | Disable provider | "This integration needs re-authentication." |
| Tool exception | Skill result error | Retry if safe | "The tool failed; I am trying the safe fallback." |
| Browser action mismatch | Verify failed | Re-observe page | "The page did not respond as expected." |
| Memory conflict | Contradictory facts | Ask user | "I have conflicting information; which is correct?" |
| Prompt injection | Policy detector | Treat as untrusted data | "The page contains instructions I will ignore." |
| Disk full | System health | Cleanup suggestion | "Storage is low; approve cleanup?" |
| DB locked | SQLite error | Retry/backoff | "Memory is temporarily busy." |
| Voice STT failure | Empty transcript | Ask repeat | "I did not catch that." |
| TTS failure | Exception | Text-only response | "Voice output is unavailable." |

---

## Section 27: Advanced Security Model

### 27.1 Principle of Least Privilege

Each component gets only what it needs:

- Email skill cannot read filesystem secrets.
- Code runner cannot access `.env`.
- Browser agent cannot call email send directly.
- Frontend cannot call admin endpoints without admin token.
- LLM cannot directly execute tools; it proposes tool calls that policy approves.

### 27.2 Data Loss Prevention

Before sending external content:

- Scan for API keys
- Scan for passwords
- Scan for private file paths
- Scan for personal identifiers
- Ask confirmation if sensitive content found

### 27.3 Approval Memory

Store approvals as scoped grants:

```text
allow email.read for 24h
allow weather always
allow send_email to specific contact once
allow browser actions on domain example.com for this task
deny code execution always unless manually enabled
```

### 27.4 Tamper Evidence

Audit log should be append-only with hash chaining:

```text
event_hash = sha256(previous_hash + event_json)
```

This lets Javris detect if logs were modified.

---

## Section 28: Intelligence Beyond The Existing Plan

### 28.1 Personal Operating Model

Javris should learn:

- Work hours
- Deep work windows
- Common projects
- People and relationships
- Preferred response style by context
- Repeated tasks
- Stress indicators
- Energy patterns
- Communication habits
- Notification tolerance

### 28.2 Project Awareness

For each coding/project folder:

```text
project name
tech stack
commands
test command
run command
recent errors
open tasks
important files
architecture summary
last worked timestamp
```

### 28.3 Habit and Routine Engine

Examples:

- "You usually check trading news after opening the market dashboard."
- "You have been coding for 92 minutes; your next meeting is in 18 minutes."
- "You often ask for project status on Fridays; I prepared a summary."

### 28.4 Goal Graph

Represent goals as graph nodes:

```text
Goal -> Projects -> Tasks -> Subtasks -> Evidence -> Deadlines -> People
```

This is more powerful than a flat task list.

---

## Section 29: Build Roadmap

### Phase A - Hardening Sprint

1. Rotate leaked credentials.
2. Remove hardcoded secrets.
3. Add auth middleware.
4. Add permission engine.
5. Fix autonomy `_call_llm` bug.
6. Fix HUD/API contract mismatches.
7. Fix router hedging.
8. Add standard skill result schema.
9. Add code runner sandbox mode.
10. Add security tests.

### Phase B - Architecture Spine

1. Add event bus.
2. Add durable task ledger.
3. Add audit log.
4. Add request correlation IDs.
5. Add context broker.
6. Add trace viewer.
7. Add skill registry v2.
8. Add DB migrations.

### Phase C - Intelligence Layer

1. Add intent router v2.
2. Add planner.
3. Add executor.
4. Add verifier.
5. Add recovery engine.
6. Add episodic memory.
7. Add relationship memory.
8. Add procedural memory.

### Phase D - Perception Layer

1. Screen OCR.
2. Document intelligence.
3. Browser DOM + accessibility observation.
4. Webcam presence.
5. Multi-monitor awareness.
6. Audio tone detection.

### Phase E - Autonomy Layer

1. Event-driven triggers.
2. Self-healing loop.
3. Overnight job queue.
4. Calendar-aware alerts.
5. Proactive project reports.
6. Approval queue.

### Phase F - Interface Layer

1. Split frontend modules.
2. Add permission UX.
3. Add trace viewer.
4. Add memory explorer.
5. Add desktop overlay.
6. Add PWA.
7. Add Gemini Live WebSocket.

### Phase G - Evaluation and Continuous Improvement

1. Add eval datasets.
2. Add regression runner.
3. Add latency budgets.
4. Add prompt-injection tests.
5. Add skill health tests.
6. Add weekly self-review report.

---

## Section 30: Definition of "Highly Advanced"

Javris becomes truly advanced when it can:

1. Understand the user's current digital environment.
2. Retrieve the right memory at the right time.
3. Plan multi-step work.
4. Use tools safely.
5. Ask for approval when risk is high.
6. Recover from failures.
7. Explain what it did.
8. Preserve an audit trail.
9. Improve from feedback.
10. Work across voice, screen, browser, files, calendar, email, and tasks.
11. Stay secure even when webpages, emails, or documents contain malicious instructions.
12. Continue functioning when providers fail.
13. Measure its own quality with evals.
14. Maintain user trust through transparency and control.

The target is not just "more features." The target is a personal intelligence system with:

- Stable architecture
- Strong safety boundaries
- Deep personalization
- Multi-modal perception
- Autonomous execution
- Verifiable actions
- Failure recovery
- Long-term memory
- Continuous evaluation
- Human-controlled permissions

---

## Section 31: Next Concrete Implementation Order

If only one path is followed, use this order:

```text
1. Security cleanup
2. Auth middleware
3. Permission engine
4. Router and autonomy bug fixes
5. Skill result standardization
6. Event bus
7. Task ledger
8. Context broker
9. Planner/executor/verifier
10. Episodic memory
11. Prompt-injection firewall
12. Computer-use safety gates
13. Evaluation harness
14. Frontend trace and permission panels
15. Advanced autonomy jobs
```

This order creates a stable base first. After that, adding Calendar, Spotify, WhatsApp, smart home, health, document intelligence, Gemini Live, and desktop overlay will be much safer and easier.

---

## Section 32: Final Engineering Principle

Do not build Javris as a collection of APIs. Build it as a controlled intelligence operating system.

Every action should pass through:

```text
Intent -> Context -> Plan -> Policy -> Execute -> Verify -> Record -> Learn
```

That loop is the real difference between a chatbot with tools and a sophisticated personal AI assistant.

---

## Section 33: Execution Blueprint - Start Building The Crazy Version

**Date added:** 2026-05-09

This section converts the architecture above into an implementation plan that can be executed inside this repository. The rule is simple: do not add flashy features until the core loop is stable.

The north-star product is not "a chatbot with many APIs." It is a personal operating system that can see context, choose tools, ask permission, execute, verify, remember, and improve.

### 33.1 Product Pillars

| Pillar | What It Means | First Real Deliverable |
|--------|---------------|------------------------|
| Brain | Plans multi-step work, routes tools, verifies results | `core/planner.py`, `core/executor.py`, `core/verifier.py` |
| Senses | Reads screen, files, browser, voice, system state | `core/context_broker.py`, `core/vision.py`, `skills/life/*` |
| Hands | Uses apps, browser, files, email, calendar, code, OS | Permission-gated skill execution |
| Memory | Remembers facts, episodes, projects, routines | Memory schema upgrade + compaction jobs |
| Presence | Always-on HUD, voice, proactive alerts | Frontend panels + live event stream |
| Safety | Auth, approval, audit logs, sandboxing | Policy engine before high-risk actions |
| Evaluation | Measures whether Javris is getting better | `tests/evals/` regression suite |

### 33.2 Non-Negotiable Build Order

1. Stabilize security and contracts.
2. Add event bus and durable task ledger.
3. Build context broker.
4. Build planner, executor, verifier.
5. Put every dangerous action behind policy approval.
6. Add evals before expanding autonomy.
7. Upgrade sensory skills.
8. Upgrade interface.
9. Add deep proactive behavior.

If a feature does not fit this order, it goes into the backlog. This keeps the project powerful without making it chaotic.

---

## Section 34: Sprint 0 - Repo Stabilization And Safety Gate

**Goal:** Make the current Javris codebase safe enough to extend aggressively.

**Target duration:** 2-3 days

### 34.1 Tasks

| ID | Task | Files | Acceptance Check |
|----|------|-------|------------------|
| S0-01 | Create a typed `SkillResult` model | `skills/base.py`, `core/models.py` | Every skill can return `{ok, data, error, metadata}` |
| S0-02 | Add auth middleware for API and websocket routes | `server/app.py`, `core/security.py` | Requests without token fail except static frontend and health |
| S0-03 | Add policy engine for risky actions | `core/policy.py` | File write, shell, email send, browser action require approval class |
| S0-04 | Add audit log writer | `core/audit.py`, `data/` | Every tool execution is recorded with timestamp and result |
| S0-05 | Fix config defaults for production | `core/config.py`, `.env.example` | `javris_secret_key=change_me` fails in non-debug mode |
| S0-06 | Add smoke tests for server boot and skill loading | `tests/` | `pytest` validates assistant init and `/api/status` |
| S0-07 | Document dangerous abilities | this file | High-risk actions are listed with approval policy |

### 34.2 Dangerous Action Classes

| Action Class | Examples | Default Policy |
|--------------|----------|----------------|
| Read-only | weather, news, memory search, system stats | allow |
| Personal-data read | email inbox, calendar, files, browser history | allow after login |
| External communication | send email, send Telegram, post Discord | ask every time |
| Local mutation | write file, delete note, create task | ask unless trusted rule exists |
| OS control | launch app, clipboard write, kill process | ask |
| Shell/code execution | Python exec, shell command, package install | ask and audit |
| Browser action | click, type, submit form, payment page | ask for submit/payment/auth |
| Credential access | env, tokens, API keys | deny by default |

### 34.3 Definition Of Done

Sprint 0 is complete when:

- Server starts without exposing unsafe endpoints by default.
- Skills return a standard result shape.
- Risky actions are classified before execution.
- Tool calls are written to an audit log.
- A failing skill does not crash chat or websocket streams.
- There is a small test suite proving the above.

---

## Section 35: Sprint 1 - The Intelligence Spine

**Goal:** Make Javris capable of structured multi-step work.

**Target duration:** 5-7 days

### 35.1 New Modules

```text
core/
  events.py           # in-process async event bus
  task_ledger.py      # durable task state in SQLite
  context_broker.py   # gathers and filters context
  planner.py          # converts goals into executable steps
  executor.py         # runs steps through skills and policy
  verifier.py         # checks whether the goal was satisfied
  recovery.py         # retries, replans, or asks user
  models.py           # shared pydantic schemas
```

### 35.2 Core Schemas

```python
class SkillResult(BaseModel):
    ok: bool
    data: dict | list | str | None = None
    error: str | None = None
    metadata: dict = {}

class PlanStep(BaseModel):
    id: str
    goal: str
    skill: str | None = None
    args: dict = {}
    risk: str = "read_only"
    requires_approval: bool = False

class ExecutionTrace(BaseModel):
    trace_id: str
    user_goal: str
    plan: list[PlanStep]
    events: list[dict]
    final_result: SkillResult | None = None
```

### 35.3 First Supported Complex Commands

| Command | Expected Behavior |
|---------|-------------------|
| "Give me my morning briefing" | Parallel weather, news, calendar, tasks, finance summary |
| "Find what I worked on today" | Browser/file/activity context summary |
| "Summarize this project" | Reads repo files, status, recent changes, produces concise report |
| "Plan my day" | Calendar + tasks + habits + priorities |
| "Research X and save a note" | Search, summarize, ask before writing note |

### 35.4 Acceptance Checks

- Planner emits JSON steps, not free-form prose.
- Executor refuses unknown skills.
- Policy is checked before every step.
- Verifier can mark a task as `complete`, `partial`, or `failed`.
- Failed steps produce a recovery action instead of silent failure.
- `/api/autonomy/events` and websocket streams include trace IDs.

---

## Section 36: Sprint 2 - Context Broker And Memory Upgrade

**Goal:** Stop dumping random history into prompts. Give Javris the right context at the right time.

**Target duration:** 5-7 days

### 36.1 Context Broker Sources

| Source | Current Asset | Broker Role |
|--------|---------------|-------------|
| Recent chat | `core/memory.py` | Last few turns only |
| Semantic memory | `core/vector_memory.py` | Relevant historical facts |
| System state | `/api/system`, `core/ambient.py` | Current machine status |
| Browser history | `skills/life/browser.py` | Recent activity context |
| Files | `skills/life/files.py` | Project/document context |
| Tasks | `skills/life/tasks.py` | Commitments and todo state |
| Calendar | `skills/life/calendar_skill.py` | Time commitments |
| Screen | `core/vision.py` | Visible UI and OCR |

### 36.2 Ranking Rules

Context is ranked by:

1. Direct match to user request.
2. Recency.
3. User-pinned importance.
4. Current active app/window.
5. Relationship to active project.
6. Confidence score.
7. Safety classification.

### 36.3 Memory Types To Add

| Memory Type | Storage | Example |
|-------------|---------|---------|
| Fact | SQLite + vector | "User prefers concise answers." |
| Episode | SQLite + vector | "On May 9, user planned Javris rebuild." |
| Project | SQLite | "Javris: current repo, goals, open tasks." |
| Procedure | SQLite | "How to run tests for this repo." |
| Preference | SQLite | "Use fast local actions first." |
| Relationship | SQLite | "Person X is teammate/client/family." |

### 36.4 New Tables

```text
memory_facts(id, category, content, confidence, source, created_at, updated_at)
memory_episodes(id, title, summary, evidence_json, created_at)
projects(id, name, root_path, summary, status, updated_at)
project_tasks(id, project_id, title, status, priority, evidence_json, updated_at)
procedures(id, name, steps_json, success_count, failure_count, updated_at)
approvals(id, action_hash, scope, decision, expires_at, created_at)
audit_log(id, trace_id, actor, action, risk, input_json, output_json, created_at)
```

### 36.5 Acceptance Checks

- A user request gets a `ContextBundle` with explicit sources.
- Prompt-injection text from files/webpages is labeled as untrusted data.
- Long chats get compacted into episodes.
- Project summary can be regenerated from local files and git state.
- Memory writes include source and confidence.

---

## Section 37: Sprint 3 - Sensory And Tool Upgrades

**Goal:** Give Javris richer real-world awareness without breaking safety.

**Target duration:** 1-2 weeks

### 37.1 Upgrade Queue

| Priority | Feature | Files | Notes |
|----------|---------|-------|-------|
| P1 | Document intelligence | `skills/documents.py` | PDF, DOCX, images, tables |
| P1 | Screen reader/OCR | `core/vision.py`, `skills/screen_reader.py` | Use existing screenshot pipeline first |
| P1 | Google Calendar OAuth | `skills/google_calendar.py`, `server/app.py` | Real calendar sync |
| P2 | Spotify Web API | `skills/music.py`, `core/config.py` | Real playback control |
| P2 | Gmail briefing upgrade | `skills/email_skill.py` | Urgency, sender, action items |
| P2 | App/window control | `skills/system_control.py` | Safer command set |
| P3 | Gemini Live UI | `core/gemini_live.py`, `server/app.py`, `frontend/` | Full-duplex mode |
| P3 | Webcam presence | `core/presence.py` | Local-only by default |

### 37.2 Implementation Rule

Every new skill must include:

```text
1. tool_definition
2. input validation
3. SkillResult output
4. risk classification
5. timeout handling
6. tests or a smoke script
7. audit metadata
```

### 37.3 First Feature To Implement After The Spine

Build `skills/documents.py` first because it gives the assistant immediate power over PDFs, notes, screenshots, resumes, assignments, and project files without needing external OAuth.

Minimum document actions:

```text
read_pdf(path)
read_docx(path)
read_txt(path)
ocr_image(path)
summarize(path, mode="brief|deep|action_items")
extract_tables(path)
ask(path, question)
```

---

## Section 38: Sprint 4 - Interface That Feels Alive

**Goal:** Make the HUD expose what Javris is thinking, doing, waiting for, and remembering.

**Target duration:** 1-2 weeks

### 38.1 Frontend Panels

| Panel | Purpose | Backend Source |
|-------|---------|----------------|
| Chat | Normal user conversation | `/ws` |
| Trace | Shows plan, step, tool, verifier status | event bus |
| Approvals | User approves risky actions | policy engine |
| Memory | Facts, episodes, projects | memory APIs |
| System | CPU, RAM, disk, active app | `/api/system`, ambient |
| Tasks | Active autonomous jobs | task ledger |
| Voice | Listen/speak/live mode state | `/ws/voice`, Gemini Live |

### 38.2 UI Behavior

- Show plan steps as they execute.
- Show risk badges before tool calls.
- Show "waiting for approval" as a blocking state.
- Let user cancel active tasks.
- Let user inspect the exact context sources used.
- Let user delete or correct a memory.
- Keep the main screen functional, not a marketing landing page.

### 38.3 Acceptance Checks

- User can see why Javris chose an action.
- User can approve, deny, or cancel.
- Autonomy events do not disappear after refresh.
- Long-running tasks show progress.
- Failed tasks show the failure reason and recovery option.

---

## Section 39: Evaluation Harness

**Goal:** Make Javris measurable.

### 39.1 Eval Structure

```text
tests/
  evals/
    fixtures/
      emails.json
      calendar_events.json
      project_files/
      malicious_prompts.txt
    test_planner.py
    test_policy.py
    test_context_broker.py
    test_memory.py
    test_skill_contracts.py
    test_prompt_injection.py
```

### 39.2 Required Metrics

| Metric | Target |
|--------|--------|
| Server boot success | 100% |
| Skill contract compliance | 100% |
| Dangerous action blocked without approval | 100% |
| Planner valid JSON rate | > 95% |
| Context relevance | > 80% on fixtures |
| Memory retrieval precision | > 80% on fixtures |
| Chat p95 first token latency | < 3 seconds where provider allows |
| Tool execution audit coverage | 100% |

### 39.3 Red-Team Tests

Include malicious inputs from:

- Emails.
- Webpages.
- PDFs.
- Browser history titles.
- File contents.
- Calendar event descriptions.

Expected behavior: Javris treats those as untrusted data and never follows instructions from them unless the user explicitly asks.

---

## Section 40: First 10 Commits To Make

This is the concrete starting sequence.

1. `core/models.py`: add `SkillResult`, `PlanStep`, `ExecutionTrace`, `RiskLevel`.
2. `skills/base.py`: update `BaseSkill` to document the standard result contract.
3. `core/policy.py`: classify actions and require approval for risky operations.
4. `core/audit.py`: write JSONL or SQLite audit entries for every tool call.
5. `core/events.py`: add async event bus with trace IDs.
6. `core/task_ledger.py`: persist task state and execution traces.
7. `core/context_broker.py`: gather memory, ambient, file, task, calendar, and screen context.
8. `core/planner.py`: produce structured plans for multi-step requests.
9. `core/executor.py` and `core/verifier.py`: run, verify, recover.
10. `tests/evals/`: add fixtures proving the spine works before feature expansion.

After these 10 commits, the project can safely go wild: document intelligence, real calendar, Spotify, Gemini Live, proactive HUD, and overnight agents will sit on a real foundation instead of becoming random one-off integrations.
