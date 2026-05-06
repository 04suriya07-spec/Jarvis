# Javris – Setup & Usage Guide

## What is Javris?

Javris is a full-stack AI personal assistant inspired by OpenJarvis, rebuilt from scratch with:

| Feature | Details |
|---|---|
| **AI Brain** | Claude (claude-sonnet-4-6) with multi-hop tool use |
| **Voice STT** | OpenAI Whisper (local) or Google Speech |
| **Voice TTS** | Microsoft Edge TTS (free neural) or ElevenLabs |
| **Cloud Storage** | Firebase Firestore (real-time sync) |
| **Local Storage** | SQLite (offline fallback) |
| **Web Dashboard** | FastAPI + custom HTML/CSS/JS |
| **Streaming** | WebSocket streaming responses |
| **Skills** | Web search, weather, news, system control, code runner, notes, scheduler |
| **Agents** | Deep Research, Morning Digest |

---

## Quick Start (Windows)

```bat
cd S:\Javris
setup.bat
```

Then edit `.env` with your API keys, then:

```bat
.venv\Scripts\activate
python main.py serve
```

Open **http://localhost:8000** in your browser.

---

## Quick Start (Linux/Mac)

```bash
cd /path/to/Javris
bash setup.sh
source .venv/bin/activate
python main.py serve
```

---

## Required API Keys

### Minimum (just AI chat):
```env
ANTHROPIC_API_KEY=sk-ant-...    # Get at console.anthropic.com
```

### For weather:
```env
WEATHER_API_KEY=...             # Free at openweathermap.org
```

### For news:
```env
NEWS_API_KEY=...                # Free at newsapi.org
```

### For cloud sync (Firebase):
1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Create a project → Firestore → Enable
3. Project Settings → Service Accounts → Generate New Private Key
4. Save the JSON as `firebase-credentials.json` in the project root
5. Set `FIREBASE_PROJECT_ID=your-project-id` in `.env`

### For premium voice (ElevenLabs):
```env
TTS_ENGINE=elevenlabs
ELEVENLABS_API_KEY=...          # elevenlabs.io
```

---

## CLI Commands

```bash
# Start web server (recommended)
python main.py serve

# Terminal chat
python main.py chat

# Voice mode (wake word: "jarvis")
python main.py voice

# Morning digest
python main.py digest --location "New York" --speak

# Deep research
python main.py research "quantum computing breakthroughs 2025"
```

---

## Architecture

```
S:\Javris\
├── main.py              ← CLI entry point
├── core\
│   ├── assistant.py     ← AI orchestrator (tool use loop)
│   ├── config.py        ← Settings (reads .env)
│   ├── logger.py        ← Rich logging
│   ├── memory.py        ← Short-term + SQLite long-term memory
│   └── voice.py         ← STT + TTS engine
├── cloud\
│   └── storage.py       ← Firebase Firestore sync
├── skills\
│   ├── web_search.py    ← DuckDuckGo + SerpAPI
│   ├── weather.py       ← OpenWeatherMap
│   ├── news.py          ← NewsAPI + DDG fallback
│   ├── system_control.py← App launcher, screenshot, clipboard
│   ├── scheduler.py     ← Reminders (APScheduler)
│   ├── code_runner.py   ← Safe Python execution
│   └── notes.py         ← Personal notes
├── agents\
│   ├── research_agent.py← Multi-hop web research
│   └── morning_digest.py← Daily briefing (text + speech)
├── server\
│   └── app.py           ← FastAPI REST + WebSocket API
└── frontend\
    └── index.html       ← Full web dashboard
```

---

## Adding Skills

Create `skills/my_skill.py`:

```python
from skills.base import BaseSkill

class MySkill(BaseSkill):
    name = "my_skill"
    tool_definition = {
        "name": "my_skill",
        "description": "What it does",
        "input_schema": {
            "type": "object",
            "properties": {"param": {"type": "string"}},
            "required": ["param"],
        },
    }

    async def run(self, param: str) -> dict:
        return {"result": f"Did something with {param}"}
```

Then register it in `core/assistant.py` → `_load_skills()`.

---

## Offline Mode

Javris works fully offline with Ollama:

```bash
# Install Ollama: https://ollama.ai
ollama pull llama3.2
```

In `.env`:
```env
JAVRIS_PRIMARY_MODEL=ollama
JAVRIS_OLLAMA_MODEL=llama3.2
STT_ENGINE=whisper_local
TTS_ENGINE=pyttsx3
```

---

## Voice Setup (Windows)

PyAudio requires Microsoft C++ Build Tools or a pre-built wheel:

```bat
pip install pipwin
pipwin install pyaudio
```

Or download the wheel from [Christoph Gohlke's site](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio).
