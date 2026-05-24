"""
Javris FastAPI Server  v3 — Personal Intelligence System + Computer-Use Agent
───────────────────────────────────────────────────────────────────────────────
Computer-Use endpoints:
  POST /api/computer/init         Connect to live Chrome or launch browser
  POST /api/computer/task         Start an autonomous browser task
  POST /api/computer/quiz         Start a quiz-completion task
  POST /api/computer/assignment   Start an assignment-filling task
  GET  /api/computer/status       Current agent status
  GET  /api/computer/tasks        All past tasks
  GET  /api/computer/task/{id}    Specific task detail + steps
  POST /api/computer/stop         Stop running task
  POST /api/computer/pause        Pause/resume
  WS   /ws/computer               Live step-by-step task progress stream
  POST /api/computer/screenshot   Take screenshot of current page
  POST /api/computer/action       Execute a single browser action manually
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import get_config
from core.logger import get_logger
from core.models import SkillResult
from core.audit import get_audit_log
from core.events import get_event_bus
from core.policy import get_policy_engine
from core.security.auth import require_api_auth, websocket_authorized
from core.gemini_live import GeminiLiveSession
from core.wake_word import WakeWordDetector
from core.computer_agent import ComputerAgent
logger = get_logger("javris.server")
cfg = get_config()
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Javris", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:3000",   # React dev server
        "http://127.0.0.1:8000",
        "app://.",                  # Electron
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

if (FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

# ── Injected dependencies ─────────────────────────────────────────
_assistant = None
_voice = None
_cloud = None
_research_agent = None
_digest_agent = None
_computer_agent = None
_mode_manager = None

# Computer-agent step subscribers (WebSocket live feed)
_computer_ws_subscribers: list[asyncio.Queue] = []
_event_bus = get_event_bus()
_policy = get_policy_engine()
_audit = get_audit_log()


api_auth = Depends(require_api_auth)


def get_assistant():
    global _assistant
    return getattr(app.state, 'assistant', _assistant)


def get_voice():
    global _voice
    return getattr(app.state, 'voice', _voice)


def set_dependencies(assistant, voice, cloud, research_agent, digest_agent):
    global _assistant, _voice, _cloud, _research_agent, _digest_agent, _mode_manager
    _assistant = assistant
    app.state.assistant = assistant
    _voice = voice
    app.state.voice = voice
    _cloud = cloud
    _research_agent = research_agent
    _digest_agent = digest_agent
    # Init mode manager wired to autonomy
    from core.modes import ModeManager
    _mode_manager = ModeManager(autonomy=assistant.autonomy if assistant else None)
    app.state.mode_manager = _mode_manager


# ── Startup / shutdown ────────────────────────────────────────────

_wake_word_detector = None

async def on_wake_word():
    logger.info("Wake word triggered! Starting Gemini Live session...")
    # Autostart Gemini live if not running
    global _live_session_task, _live_session
    if not _live_session_task or _live_session_task.done():
        _live_session = GeminiLiveSession(mode="video")
        _live_session_task = asyncio.create_task(_live_session.run())

async def _init_app_assistant():
    """Fallback initialization for when Uvicorn re-imports the module in a worker process."""
    from core.assistant import Assistant
    from core.voice import VoiceEngine
    from cloud.storage import CloudStorage
    from agents.research_agent import ResearchAgent
    from agents.morning_digest import MorningDigestAgent

    cloud = CloudStorage()
    cloud.init()
    
    voice = VoiceEngine()
    await voice.init()
    
    assistant = Assistant()
    assistant._cloud = cloud
    assistant._voice = voice
    await assistant.init()
    
    research_agent = ResearchAgent(assistant=assistant)
    digest_agent = MorningDigestAgent(assistant=assistant, voice=voice)
    
    return assistant, voice, cloud, research_agent, digest_agent

@app.on_event("startup")
async def startup():
    async def _do_init():
        global _assistant, _voice, _cloud, _research_agent, _digest_agent
        if _assistant is None:
            logger.info("Initializing Assistant in-app (background task)...")
            try:
                _assistant, _voice, _cloud, _research_agent, _digest_agent = await _init_app_assistant()
                app.state.assistant = _assistant
                app.state.voice = _voice
                
                if cfg.javris_autonomy_enabled:
                    _assistant.start_autonomy()
                    logger.info("Autonomy engine started.")
                
                logger.info("Background startup complete. Javris is ready.")
            except Exception as e:
                logger.error(f"Background startup failed: {e}", exc_info=True)

    asyncio.create_task(_do_init())
    logger.info("Server port open. AI models loading in background...")
        
    # _wake_word_detector = WakeWordDetector(callback=on_wake_word)
    # _wake_word_detector.start()


@app.on_event("shutdown")
async def shutdown():
    global _wake_word_detector
    if _wake_word_detector:
        _wake_word_detector.stop()
    if _assistant:
        await _assistant.close()


# ── Pydantic models ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class SpeakRequest(BaseModel):
    text: str

class ResearchRequest(BaseModel):
    topic: str
    depth: int = 3

class DigestRequest(BaseModel):
    location: str = ""
    speak: bool = False

class MemorySearchRequest(BaseModel):
    query: str

class RememberRequest(BaseModel):
    category: str
    content: str

class PersonalityUpdateRequest(BaseModel):
    owner_name: Optional[str] = None
    tone: Optional[str] = None
    response_length: Optional[str] = None
    domains: Optional[list[str]] = None
    wake_hour: Optional[int] = None
    speak_proactively: Optional[bool] = None
    proactive_interval: Optional[int] = None
    preferred_weather_location: Optional[str] = None
    use_emojis: Optional[bool] = None

class AutonomyTriggerRequest(BaseModel):
    event_type: str
    message: str
    priority: str = "medium"

class AutonomyTaskRequest(BaseModel):
    goal: str

class ApprovalRequest(BaseModel):
    action_hash: str
    ttl_seconds: int = 600

class TaskRequest(BaseModel):
    action: str
    task_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = "medium"
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    due_date: Optional[str] = None
    context: Optional[str] = None
    filter_status: Optional[str] = "todo"
    query: Optional[str] = None


# ── Core routes ───────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    p = FRONTEND_DIR / "index.html"
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>Javris</h1>")


@app.get("/api/status")
async def status():
    assistant = get_assistant()
    pers = assistant.personality if assistant else None
    intel = assistant.intelligence if assistant else None
    return {
        "status": "online" if assistant else "loading",
        "ready": assistant is not None,
        "version": "2.0.0",
        "assistant": assistant is not None,
        "voice": _voice is not None,
        "cloud": _cloud.available if _cloud else False,
        "model": cfg.javris_primary_model,
        "tts_engine": cfg.tts_engine,
        "stt_engine": cfg.stt_engine,
        "owner": pers.owner_name if pers else "Unknown",
        "autonomy_running": (
            _assistant.autonomy._running if _assistant else False
        ),
        "autonomy_events": (
            len(_assistant.autonomy._event_log) if _assistant else 0
        ),
        "intel_facts": len(intel.user_facts) if intel else 0,
        "intel_patterns": len(intel.patterns) if intel else 0,
        "timestamp": time.time(),
    }


@app.get("/api/system")
async def system_health():
    """Live system vitals for the HUD: CPU, RAM, disk, ambient context."""
    import psutil
    cpu   = psutil.cpu_percent(interval=0.2)
    mem   = psutil.virtual_memory()
    disk_path = "C:\\" if os.name == "nt" else "/"
    disk  = psutil.disk_usage(disk_path)
    net   = psutil.net_io_counters()

    ambient_ctx = {}
    if _assistant and hasattr(_assistant, "_ambient"):
        ambient_ctx = _assistant._ambient.snapshot.to_dict()

    return {
        "cpu_percent":  round(cpu, 1),
        "cpu":          round(cpu, 1),
        "ram_percent":  round(mem.percent, 1),
        "memory":       round(mem.percent, 1),
        "ram_used_gb":  round(mem.used / 1e9, 2),
        "ram_total_gb": round(mem.total / 1e9, 2),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "net_sent_mb":  round(net.bytes_sent / 1e6, 1),
        "net_recv_mb":  round(net.bytes_recv / 1e6, 1),
        "ambient":      ambient_ctx,
        "timestamp":    time.time(),
    }


@app.get("/api/llm/health")
async def llm_health():
    """Per-provider circuit breaker state, UCB1 scores, latency percentiles, cache stats."""
    if not _assistant or not _assistant._router:
        return {"error": "Router not initialised", "providers": []}
    return _assistant._router.health_report()


@app.post("/api/llm/reset/{provider}", dependencies=[api_auth])
async def llm_reset_circuit(provider: str):
    """Manually reset a provider's circuit breaker (admin)."""
    if not _assistant or not _assistant._router:
        raise HTTPException(503, "Router not initialised")
    ok = _assistant._router.reset_circuit(provider)
    if not ok:
        raise HTTPException(404, f"Provider '{provider}' not found")
    return {"status": "reset", "provider": provider}


@app.post("/api/llm/cache/invalidate", dependencies=[api_auth])
async def llm_cache_invalidate():
    """Clear the LLM response cache."""
    if not _assistant or not _assistant._router:
        raise HTTPException(503, "Router not initialised")
    await _assistant._router.invalidate_cache()
    return {"status": "cache cleared"}


# ── Chat ──────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Assistant not initialised")
    try:
        reply = await assistant.chat(req.message)
        return {"reply": reply, "session_id": assistant.memory.short.session_id}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(500, str(e))


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    if not websocket_authorized(websocket):
        await websocket.send_json({"type": "error", "text": "Unauthorized"})
        await websocket.close()
        return
    logger.info("Chat WS connected")
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            user_msg = payload.get("message", "")
            if not user_msg:
                continue

            assistant = get_assistant()
            if not assistant:
                await websocket.send_json({"type": "error", "text": "Not ready"})
                continue

            await websocket.send_json({"type": "start"})
            full = ""
            async for chunk in assistant.stream_chat(user_msg):
                full += chunk
                await websocket.send_json({"type": "chunk", "text": chunk})

            await websocket.send_json({
                "type": "done",
                "session_id": assistant.memory.short.session_id,
            })
    except WebSocketDisconnect:
        logger.info("Chat WS disconnected")
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ── Autonomy WebSocket (live event feed) ─────────────────────────

@app.websocket("/ws")
async def ws_unified(websocket: WebSocket):
    """
    Unified WebSocket — multiplexes chat streaming + autonomy events.
    Frontend sends: {"type":"chat","message":"..."}
    Server sends:
      {"type":"chunk","text":"..."}        — streaming chat token
      {"type":"done","session_id":"..."}   — chat complete
      {"type":"autonomy_event",...}        — autonomy/ambient push
      {"type":"heartbeat","ts":...}        — keepalive
    """
    await websocket.accept()
    if not websocket_authorized(websocket):
        await websocket.send_json({"type": "error", "text": "Unauthorized"})
        await websocket.close()
        return
    logger.info("Unified WS connected")

    assistant = get_assistant()
    if not assistant:
        await websocket.send_json({"type": "error", "text": "Assistant not ready"})
        await websocket.close()
        return

    autonomy_q = assistant.autonomy.subscribe()

    async def _push_autonomy():
        """Background task: forward autonomy events to the WS."""
        while True:
            try:
                event = await asyncio.wait_for(autonomy_q.get(), timeout=25)
                await websocket.send_json({"type": "autonomy_event", **event})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
            except Exception:
                break

    push_task = asyncio.create_task(_push_autonomy())

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            msg_type = payload.get("type", "chat")

            if msg_type == "chat":
                user_msg = payload.get("message", "")
                if not user_msg:
                    continue
                await websocket.send_json({"type": "start"})
                full = ""
                async for chunk in assistant.stream_chat(user_msg):
                    full += chunk
                    await websocket.send_json({"type": "chunk", "text": chunk})
                await websocket.send_json({
                    "type": "done",
                    "session_id": assistant.memory.short.session_id,
                })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})

    except WebSocketDisconnect:
        logger.info("Unified WS disconnected")
    except Exception as e:
        logger.debug(f"Unified WS error: {e}")
    finally:
        push_task.cancel()
        assistant.autonomy.unsubscribe(autonomy_q)


@app.websocket("/ws/autonomy")
async def ws_autonomy(websocket: WebSocket):
    """Push autonomy events in real-time to the dashboard."""
    await websocket.accept()
    if not websocket_authorized(websocket):
        await websocket.send_json({"error": "Unauthorized"})
        await websocket.close()
        return
    logger.info("Autonomy WS connected")

    if not _assistant:
        await websocket.send_json({"error": "No assistant"})
        await websocket.close()
        return

    q = _assistant.autonomy.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
    except WebSocketDisconnect:
        logger.info("Autonomy WS disconnected")
    except Exception as e:
        logger.debug(f"Autonomy WS error: {e}")
    finally:
        _assistant.autonomy.unsubscribe(q)


# ── Autonomy REST ─────────────────────────────────────────────────

@app.get("/api/autonomy/events")
async def get_autonomy_events(
    limit: int = Query(50),
    event_type: str = Query(""),
):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    events = assistant.autonomy.get_recent_events(limit=limit, event_type=event_type)
    stats = assistant.autonomy.get_stats()
    return {"events": events, "stats": stats}


@app.post("/api/autonomy/trigger", dependencies=[api_auth])
async def trigger_autonomy(req: AutonomyTriggerRequest):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    await assistant.autonomy.trigger(req.event_type, req.message, req.priority)
    return {"status": "triggered"}

@app.post("/api/autonomy/task", dependencies=[api_auth])
async def trigger_autonomous_task(req: AutonomyTaskRequest):
    """Start an autonomous task driven by Planner and Executor."""
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    
    # We trigger the background execution
    asyncio.create_task(assistant.autonomy.execute_autonomous_task(req.goal))
    return {"status": "task_started", "goal": req.goal}


@app.post("/api/autonomy/dismiss/{event_id}", dependencies=[api_auth])
async def dismiss_event(event_id: str):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    assistant.autonomy.dismiss(event_id)
    return {"status": "dismissed"}


@app.post("/api/policy/approve", dependencies=[api_auth])
async def approve_action(req: ApprovalRequest):
    """Approve a pending action hash for a short time window."""
    _policy.approve(req.action_hash, ttl_seconds=req.ttl_seconds)
    _audit.write(
        action="policy:approve",
        actor="user",
        input_data=req.model_dump(),
        decision="approved",
    )
    await _event_bus.publish("approval_granted", req.model_dump())
    return {"status": "approved", "action_hash": req.action_hash, "ttl_seconds": req.ttl_seconds}


# ── Gemini Live ───────────────────────────────────────────────────

_live_session_task = None
_live_session = None

@app.post("/api/gemini-live/start")
async def start_gemini_live():
    global _live_session_task, _live_session
    if _live_session_task and not _live_session_task.done():
        return {"status": "already_running"}
    
    _live_session = GeminiLiveSession(mode="video")
    _live_session_task = asyncio.create_task(_live_session.run())
    return {"status": "started"}

@app.post("/api/gemini-live/stop")
async def stop_gemini_live():
    global _live_session
    if _live_session:
        await _live_session.stop()
        _live_session = None
    return {"status": "stopped"}

# ── Intelligence ──────────────────────────────────────────────────

@app.get("/api/intelligence")
async def get_intelligence():
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    intel = assistant.intelligence
    return {
        "stats": intel.get_stats(),
        "facts": intel.get_all_facts(),
        "patterns": intel.get_all_patterns(),
        "summary": intel.build_summary(),
    }


@app.post("/api/intelligence/analyse")
async def force_analyse():
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    msgs = [m.to_dict() for m in assistant.memory.short.get_history()]
    await assistant.intelligence.analyse(msgs)
    return {"status": "analysed", "facts": len(assistant.intelligence.user_facts)}


# ── Personality ───────────────────────────────────────────────────

@app.get("/api/personality")
async def get_personality_profile():
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    return assistant.personality.to_dict()


@app.put("/api/personality")
async def update_personality(req: PersonalityUpdateRequest):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    assistant.update_personality(**updates)
    return {"status": "updated", "profile": assistant.personality.to_dict()}


# ── Sessions / Memory ─────────────────────────────────────────────

@app.get("/api/sessions")
async def get_sessions():
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    sessions = await assistant.memory.long.get_sessions(limit=20)
    if _cloud and _cloud.available:
        cloud_sessions = _cloud.get_sessions(limit=20)
        existing = {s["session_id"] for s in sessions}
        for cs in cloud_sessions:
            if cs.get("session_id") not in existing:
                sessions.append(cs)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    messages = await assistant.memory.long.get_session_messages(session_id)
    return {"session_id": session_id, "messages": messages}


@app.post("/api/memory/search")
async def memory_search(req: MemorySearchRequest):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    return {"query": req.query, "results": await assistant.search_memory(req.query)}


@app.post("/api/memory/remember")
async def remember(req: RememberRequest):
    assistant = get_assistant()
    if not assistant:
        raise HTTPException(503, "Not ready (Assistant missing)")
    await assistant.remember(req.category, req.content)
    return {"status": "remembered"}


@app.get("/api/memory/facts")
async def get_facts(category: Optional[str] = None):
    if not _assistant:
        raise HTTPException(503, "Not ready")
    return {"facts": await _assistant.memory.long.get_facts(category)}


@app.post("/api/session/new")
async def new_session():
    if not _assistant:
        raise HTTPException(503, "Not ready")
    _assistant.new_session()
    return {"session_id": _assistant.memory.short.session_id}


# ── Tasks ─────────────────────────────────────────────────────────

@app.post("/api/tasks")
async def tasks_api(req: TaskRequest):
    if not _assistant:
        raise HTTPException(503, "Not ready")
    skill = _assistant._skill_registry.get("tasks")
    if not skill:
        raise HTTPException(503, "Tasks skill not loaded")
    params = {k: v for k, v in req.model_dump().items() if v is not None and k != "action"}
    result = await skill.run(action=req.action, **params)
    return result


# ── Calendar ──────────────────────────────────────────────────────

@app.get("/api/calendar")
async def calendar_api(action: str = "list_upcoming", days: int = 7):
    if not _assistant:
        raise HTTPException(503, "Not ready")
    skill = _assistant._skill_registry.get("calendar")
    if not skill:
        raise HTTPException(503, "Calendar skill not loaded")
    return await skill.run(action=action, days=days)


# ── Browser ───────────────────────────────────────────────────────

@app.get("/api/browser/history")
async def browser_history(hours: int = 24, query: str = "", limit: int = 20):
    if not _assistant:
        raise HTTPException(503, "Not ready")
    skill = _assistant._skill_registry.get("browser")
    if not skill:
        raise HTTPException(503, "Browser skill not loaded")
    if query:
        return await skill.run(action="search_history", query=query, limit=limit)
    return await skill.run(action="recent_history", hours=hours, limit=limit)


# ── Files ─────────────────────────────────────────────────────────

@app.get("/api/files")
async def files_api(action: str = "list", path: str = ".", query: str = "", hours: int = 24):
    if not _assistant:
        raise HTTPException(503, "Not ready")
    skill = _assistant._skill_registry.get("files")
    if not skill:
        raise HTTPException(503, "Files skill not loaded")
    params = {"path": path}
    if query:
        params["query"] = query
    if action == "recent_changes":
        params["hours"] = hours
    return await skill.run(action=action, **params)


# ── Voice ─────────────────────────────────────────────────────────

@app.post("/api/voice/listen_once")
async def voice_listen_once():
    """
    Trigger a single listen → AI → speak cycle with Sentence Streaming.
    Javris starts speaking sentences as they are generated.
    """
    voice = get_voice()
    assistant = get_assistant()
    if not voice:
        raise HTTPException(503, "Voice not initialised")
    if not assistant:
        raise HTTPException(503, "Assistant not ready")

    try:
        # 1. Listen (Now dynamic VAD)
        text = await voice.listen()
        if not text:
            return {"transcript": "", "reply": ""}

        # 2. Stream AI Response and Play Sentences in real-time
        full_reply = ""
        sentence_buffer = ""
        
        async def _process_stream():
            nonlocal sentence_buffer, full_reply
            logger.info("AI starting to think...")
            async for chunk in assistant.stream_chat(text):
                full_reply += chunk
                sentence_buffer += chunk
                
                # Aggressive splitting for lower latency: period, question, exclamation, comma, semicolon, newline
                if any(p in chunk for p in [".", "!", "?", ",", ";", "\n"]):
                    utterance = sentence_buffer.strip()
                    if len(utterance) > 10: # Only speak if it's a meaningful fragment
                        logger.info(f"Speaking segment: '{utterance}'")
                        asyncio.create_task(voice.speak(utterance))
                        sentence_buffer = ""

            # Speak any remaining text at the end
            final_part = sentence_buffer.strip()
            if final_part:
                logger.info(f"Speaking final segment: '{final_part}'")
                await voice.speak(final_part)
            
            logger.info("AI finished speaking.")

        # Run the stream process
        asyncio.create_task(_process_stream())

        return {"transcript": text, "reply": "Thinking..."}
    except Exception as e:
        logger.error(f"Voice listen_once error: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/voice/speak")
async def speak(req: SpeakRequest):
    voice = get_voice()
    if not voice:
        raise HTTPException(503, "Voice not initialised")
    asyncio.create_task(voice.speak(req.text))
    return {"status": "speaking"}


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    """
    Receive raw audio bytes from browser microphone,
    transcribe via Whisper, return text + AI reply.
    """
    await websocket.accept()
    logger.info("Voice WS connected")
    try:
        while True:
            data = await websocket.receive_bytes()
            if not _voice:
                await websocket.send_json({"error": "Voice not ready"})
                continue

            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
                f.write(data)
                tmp = f.name

            try:
                if _voice._stt:
                    text = await asyncio.get_running_loop().run_in_executor(
                        None, _voice._stt.transcribe, tmp
                    )
                else:
                    text = ""
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

            if text and _assistant:
                await websocket.send_json({"type": "transcript", "text": text})
                reply = await _assistant.chat(text)
                await websocket.send_json({"type": "reply", "text": reply})
                if _voice:
                    asyncio.create_task(_voice.speak(reply))
            else:
                await websocket.send_json({"type": "transcript", "text": ""})
    except WebSocketDisconnect:
        logger.info("Voice WS disconnected")


# ── Research / Digest ─────────────────────────────────────────────

@app.post("/api/research")
async def research(req: ResearchRequest):
    if not _research_agent:
        raise HTTPException(503, "Research agent not ready")
    return await _research_agent.research(req.topic, depth=req.depth)


@app.post("/api/digest")
async def digest(req: DigestRequest):
    if not _digest_agent:
        raise HTTPException(503, "Digest agent not ready")
    return await _digest_agent.run(location=req.location, speak=req.speak)


# ── Google OAuth ──────────────────────────────────────────────────

@app.get("/auth/google")
async def google_auth_start():
    return JSONResponse({
        "message": "Place google_credentials.json in data/ folder and restart."
    })


# ── Modes ─────────────────────────────────────────────────────────

class ModeSwitchRequest(BaseModel):
    mode_id: str

@app.get("/api/modes")
async def list_modes():
    """List all available workspace modes."""
    if not _mode_manager:
        raise HTTPException(503, "Mode manager not ready")
    return {
        "current": _mode_manager.current_id,
        "modes": _mode_manager.list_modes(),
    }

@app.post("/api/modes/switch")
async def switch_mode(req: ModeSwitchRequest):
    """Switch active workspace mode. Broadcasts to dashboard via WebSocket."""
    if not _mode_manager:
        raise HTTPException(503, "Mode manager not ready")
    result = await _mode_manager.switch(req.mode_id)
    return result

@app.get("/api/modes/current")
async def current_mode():
    if not _mode_manager:
        raise HTTPException(503, "Mode manager not ready")
    return _mode_manager.current.to_dict()


# ── Config / API Keys ─────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    anthropic_api_key: str = ""

@app.post("/api/config/apikey", dependencies=[api_auth])
async def set_api_key(req: ApiKeyRequest):
    """
    Hot-swap the Anthropic API key without restarting.
    Also writes it to .env for persistence.
    """
    from pathlib import Path
    import anthropic

    key = req.anthropic_api_key.strip()
    if not key:
        return {"status": "error", "message": "Empty key"}

    # Test the key quickly
    try:
        test_client = anthropic.AsyncAnthropic(api_key=key)
        # Quick validation ping (models.list doesn't cost tokens)
    except Exception as e:
        return {"status": "error", "message": f"Invalid key: {e}"}

    # Update the assistant's client live
    if _assistant:
        import anthropic as _anthropic
        _assistant._client = _anthropic.AsyncAnthropic(api_key=key)
        logger.info("Claude API key updated live — Claude is now active")

    # Persist to .env
    env_path = Path(__file__).parent.parent / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("ANTHROPIC_API_KEY="):
                new_lines.append(f"ANTHROPIC_API_KEY={key}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"ANTHROPIC_API_KEY={key}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not write .env: {e}")

    return {"status": "saved", "message": "Claude API key saved — Claude is now active"}


# ══════════════════════════════════════════════════════════════════
# COMPUTER-USE AGENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════

class VoiceCommandRequest(BaseModel):
    text: str
    context: str = ""   # current panel/state for better routing

class VoiceCommandResponse(BaseModel):
    response: str
    action_taken: str
    data: dict = {}
    is_ui_command: bool = False
    ui_params: dict = {}
    speak: bool = True


@app.post("/api/voice/command")
async def voice_command(req: VoiceCommandRequest):
    """
    Fast voice command endpoint.
    Parses spoken text and routes to the correct action.
    Returns response text + action metadata so client can
    execute UI changes AND speak the reply simultaneously.
    """
    from core.voice_commands import parse_command, execute_command

    cmd = parse_command(req.text)

    if cmd.is_ui_command:
        return {
            "response": "",
            "action_taken": "ui",
            "is_ui_command": True,
            "ui_params": cmd.params,
            "speak": False,
        }

    if not _assistant:
        return {"response": "Assistant not ready.", "action_taken": "error", "is_ui_command": False, "ui_params": {}, "speak": True}

    result = await execute_command(cmd, _assistant, _assistant.autonomy if _assistant else None)
    return {
        **result,
        "is_ui_command": False,
        "ui_params": {},
        "speak": True,
    }


class ComputerInitRequest(BaseModel):
    use_live_chrome: bool = True    # True = connect to existing Chrome
    cdp_port: int = 9222            # Chrome debug port

class ComputerTaskRequest(BaseModel):
    goal: str
    url: str = ""
    max_steps: int = 50

class ComputerQuizRequest(BaseModel):
    url: str
    subject_context: str = ""
    max_steps: int = 80

class ComputerAssignmentRequest(BaseModel):
    url: str
    instructions: str = ""
    max_steps: int = 60

class ComputerActionRequest(BaseModel):
    action: str          # click | type | navigate | scroll | press_key | screenshot
    selector: str = ""
    text: str = ""
    url: str = ""
    value: str = ""
    x_percent: float = 0
    y_percent: float = 0


def _get_computer_agent():
    global _computer_agent
    return _computer_agent


async def _ensure_computer_agent(use_live: bool = True) -> ComputerAgent:
    global _computer_agent
    if _computer_agent is None:
        _computer_agent = ComputerAgent()
    if not _computer_agent.browser.connected:
        await _computer_agent.init(use_live_chrome=use_live)
    return _computer_agent


def _broadcast_step(step) -> None:
    """Push a task step to all connected WebSocket clients."""
    payload = {
        "step": step.step_num,
        "action": step.action_type,
        "description": step.description,
        "result": step.result,
        "success": step.success,
        "timestamp": step.timestamp,
        "has_screenshot": bool(step.screenshot_b64),
    }
    dead = []
    for q in _computer_ws_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _computer_ws_subscribers.remove(q)
        except ValueError:
            pass


@app.post("/api/computer/init", dependencies=[api_auth])
async def computer_init(req: ComputerInitRequest):
    """Connect browser agent to live Chrome or launch new browser."""
    agent = await _ensure_computer_agent(use_live=req.use_live_chrome)
    return {"status": "ready", "browser": agent.browser.get_status()}


@app.get("/api/computer/status")
async def computer_status():
    agent = _get_computer_agent()
    if not agent:
        return {"status": "not_initialised", "browser": {"connected": False}}
    return {"status": "ready", **agent.get_status()}


@app.post("/api/computer/task", dependencies=[api_auth])
async def computer_task(req: ComputerTaskRequest):
    """Start a generic autonomous browser task."""
    agent = await _ensure_computer_agent()

    async def run():
        await agent.run_task(
            goal=req.goal,
            url=req.url,
            max_steps=req.max_steps,
            on_step=_broadcast_step,
        )

    asyncio.create_task(run())
    return {"status": "started", "goal": req.goal}


@app.post("/api/computer/quiz", dependencies=[api_auth])
async def computer_quiz(req: ComputerQuizRequest):
    """Start autonomous quiz completion."""
    agent = await _ensure_computer_agent()

    async def run():
        await agent.complete_quiz(
            url=req.url,
            subject_context=req.subject_context,
            on_step=_broadcast_step,
        )

    asyncio.create_task(run())
    return {
        "status": "started",
        "mode": "quiz_completion",
        "url": req.url,
        "note": "Watch the browser — Javris is completing the quiz in real-time.",
    }


@app.post("/api/computer/assignment", dependencies=[api_auth])
async def computer_assignment(req: ComputerAssignmentRequest):
    """Start autonomous assignment filling."""
    agent = await _ensure_computer_agent()

    async def run():
        await agent.fill_assignment(
            url=req.url,
            instructions=req.instructions,
            on_step=_broadcast_step,
        )

    asyncio.create_task(run())
    return {
        "status": "started",
        "mode": "assignment_fill",
        "url": req.url,
    }


@app.get("/api/computer/tasks")
async def computer_tasks():
    agent = _get_computer_agent()
    if not agent:
        return {"tasks": []}
    return {"tasks": agent.get_all_tasks()}


@app.get("/api/computer/task/{task_id}")
async def computer_task_detail(task_id: str):
    agent = _get_computer_agent()
    if not agent:
        raise HTTPException(503, "Computer agent not ready")
    task = agent.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        **task.to_dict(),
        "all_steps": [
            {
                "step": s.step_num,
                "action": s.action_type,
                "description": s.description,
                "result": s.result,
                "success": s.success,
            }
            for s in task.steps
        ],
    }


@app.post("/api/computer/stop", dependencies=[api_auth])
async def computer_stop():
    agent = _get_computer_agent()
    if agent:
        agent.stop()
    return {"status": "stop_requested"}


@app.post("/api/computer/pause", dependencies=[api_auth])
async def computer_pause(paused: bool = True):
    agent = _get_computer_agent()
    if agent:
        if paused:
            agent.pause()
        else:
            agent.resume()
    return {"status": "paused" if paused else "resumed"}


@app.post("/api/computer/screenshot", dependencies=[api_auth])
async def computer_screenshot():
    """Take a screenshot of the current browser page."""
    agent = _get_computer_agent()
    if not agent or not agent.browser.connected:
        # Fall back to screen screenshot
        from core.vision import VisionEngine
        v = VisionEngine()
        state = await v.screenshot(save=True)
        return {"source": "screen", "screenshot_b64": state.image_b64, "path": state.file_path}
    b64 = await agent.browser.page_screenshot()
    return {"source": "browser", "screenshot_b64": b64}


@app.post("/api/computer/action", dependencies=[api_auth])
async def computer_action(req: ComputerActionRequest):
    """Execute a single manual browser action."""
    agent = await _ensure_computer_agent()
    br = agent.browser

    result = None
    if req.action == "click":
        result = await br.click(selector=req.selector, text=req.text, x_percent=req.x_percent, y_percent=req.y_percent)
    elif req.action == "type":
        result = await br.type_text(selector=req.selector, text=req.text)
    elif req.action == "navigate":
        result = await br.goto(req.url)
    elif req.action == "scroll":
        result = await br.scroll(req.value or "down")
    elif req.action == "press_key":
        result = await br.press_key(req.value or req.text or "Enter")
    elif req.action == "screenshot":
        b64 = await br.page_screenshot()
        return {"success": True, "screenshot_b64": b64}
    else:
        return {"error": f"Unknown action: {req.action}"}

    return {"success": result.success, "detail": result.detail, "error": result.error}


@app.websocket("/ws/computer")
async def ws_computer(websocket: WebSocket):
    """
    Live stream of computer-agent steps.
    Sends a JSON event for every action Javris takes.
    """
    await websocket.accept()
    if not websocket_authorized(websocket):
        await websocket.send_json({"error": "Unauthorized"})
        await websocket.close()
        return
    logger.info("Computer WS connected")

    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _computer_ws_subscribers.append(q)

    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=20)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
    except WebSocketDisconnect:
        logger.info("Computer WS disconnected")
    except Exception as e:
        logger.debug(f"Computer WS error: {e}")
    finally:
        try:
            _computer_ws_subscribers.remove(q)
        except ValueError:
            pass


# ── Storage endpoints ─────────────────────────────────────────────

@app.get("/api/storage/status")
async def storage_status():
    """Storage tier status and disk usage."""
    return _assistant.storage.status()


@app.get("/api/storage/files")
async def storage_list_files(category: str | None = None):
    """List files — local disk usage + Supabase metadata."""
    local = _assistant.storage.local.list_category(category or "images")
    supabase = await _assistant.storage.list_files(category)
    return {
        "local": local,
        "supabase": supabase,
        "disk_usage": _assistant.storage.disk_usage(),
        "degoo_pending": _assistant.storage.degoo_pending(),
    }


@app.get("/api/storage/history")
async def storage_chat_history(session_id: str | None = None, limit: int = 100):
    """Retrieve chat history from Supabase."""
    return await _assistant.storage.get_history(session_id, limit)


@app.get("/api/storage/preferences")
async def storage_get_prefs():
    """Retrieve all user preferences from Supabase."""
    return await _assistant.storage.get_all_prefs()


@app.post("/api/storage/preferences/{key}")
async def storage_set_pref(key: str, request: Request):
    """Set a user preference in Supabase."""
    body = await request.json()
    await _assistant.storage.set_pref(key, body.get("value"))
    return {"ok": True, "key": key}


@app.post("/api/storage/sync/intelligence")
async def storage_sync_intelligence():
    """Manually sync IntelligenceEngine state to Supabase ai_memory."""
    await _assistant.storage.sync_intelligence(_assistant.intelligence)
    return {"ok": True, "synced": "intelligence"}


@app.post("/api/storage/cleanup")
async def storage_cleanup(temp_hours: int = 24):
    """Clean up old temp files."""
    result = await _assistant.storage.cleanup(temp_hours)
    return result


@app.get("/api/storage/degoo/setup")
async def storage_degoo_setup():
    """Return Degoo setup instructions."""
    return {
        "instructions": _assistant.storage.degoo_instructions(),
        "sync_folder": str(cfg.degoo_sync_path),
        "pending_files": _assistant.storage.degoo_pending(),
    }


# ── Vector / Semantic Memory routes ──────────────────────────────
# (powered by core/vector_memory.py — ChromaDB backend)

class SemanticSearchRequest(BaseModel):
    query: str
    n: int = 5


@app.post("/api/memory/semantic-search")
async def memory_semantic_search(req: SemanticSearchRequest):
    """Semantic (vector) search over all past conversations and facts."""
    if not _assistant:
        raise HTTPException(503, "Assistant not initialised")
    results = await _assistant.memory.semantic_search(req.query, n=req.n)
    return {"query": req.query, "results": results}


@app.get("/api/memory/vector-stats")
async def memory_vector_stats():
    """Return ChromaDB vector store statistics."""
    if not _assistant:
        raise HTTPException(503, "Assistant not initialised")
    return _assistant.memory.vector_stats()


# ── Skills catalogue route ────────────────────────────────────────

@app.get("/api/skills")
async def list_skills():
    """Return all registered skill names and descriptions."""
    if not _assistant:
        raise HTTPException(503, "Assistant not initialised")
    skills = []
    seen = set()
    for name, skill in _assistant._skill_registry.items():
        sid = id(skill)
        if sid not in seen:
            seen.add(sid)
            skills.append({
                "name": skill.name,
                "description": skill.description,
                "aliases": getattr(skill, "aliases", []),
                "has_tool": skill.tool_definition is not None,
            })
    return {"count": len(skills), "skills": skills}


@app.post("/api/skills/{skill_name}", dependencies=[api_auth])
async def run_skill(skill_name: str, request: Request):
    """Direct skill invocation endpoint. POST body = skill kwargs (JSON)."""
    if not _assistant:
        raise HTTPException(503, "Assistant not initialised")
    skill = _assistant._skill_registry.get(skill_name)
    if not skill:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    decision = _policy.evaluate(skill_name, body)
    if not decision.allowed:
        result = SkillResult(
            ok=False,
            error=decision.reason,
            metadata={
                "approval_required": decision.requires_approval,
                "risk": decision.risk.value,
                "action_hash": decision.action_hash,
                "skill": skill_name,
            },
        )
        _audit.write(
            action=f"skill:{skill_name}",
            actor="api",
            risk=decision.risk,
            input_data=body,
            result=result,
            decision="blocked",
        )
        return {"skill": skill_name, "result": result.model_dump()}
    try:
        raw = await skill.run(**body)
        result = skill.normalize_result(raw) if hasattr(skill, "normalize_result") else SkillResult.from_raw(raw)
        _audit.write(
            action=f"skill:{skill_name}",
            actor="api",
            risk=decision.risk,
            input_data=body,
            result=result,
            decision="executed",
        )
        return {"skill": skill_name, "result": result.model_dump()}
    except Exception as e:
        _audit.write(
            action=f"skill:{skill_name}",
            actor="api",
            risk=decision.risk,
            input_data=body,
            result={"error": str(e)},
            decision="error",
        )
        raise HTTPException(500, f"Skill error: {e}")
