"""
Javris – Main Entry Point  v2
──────────────────────────────
Commands:
    python main.py serve        Web server + autonomy engine
    python main.py chat         Terminal chat
    python main.py voice        Continuous voice mode
    python main.py digest       Morning digest
    python main.py research <topic>
    python main.py setup        First-run personality setup wizard
"""

from __future__ import annotations

import asyncio
import sys
if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown

console = Console()


def banner():
    console.print(Panel.fit(
        "[bold cyan]J A V R I S[/bold cyan]  [dim]v2.0 — Personal Intelligence System[/dim]",
        border_style="cyan",
    ))


async def _init_all(with_voice: bool = False):
    from core.logger import get_logger
    from core.assistant import Assistant
    from core.voice import VoiceEngine
    from cloud.storage import CloudStorage
    from agents.research_agent import ResearchAgent
    from agents.morning_digest import MorningDigestAgent

    log = get_logger("javris.main")

    # Cloud
    cloud = CloudStorage()
    cloud_ok = cloud.init()
    log.info(f"Cloud: {'connected' if cloud_ok else 'local only'}")

    # Assistant (wires personality + intelligence + autonomy internally)
    assistant = Assistant()
    assistant._cloud = cloud

    # Voice
    voice_engine = None
    if with_voice:
        voice_engine = VoiceEngine()
        assistant._voice = voice_engine

    await assistant.init()

    if with_voice:
        await voice_engine.init()
        # Update autonomy with voice ref after both are ready
        assistant.autonomy._voice = voice_engine

    # Agents
    research_agent = ResearchAgent(assistant=assistant)
    digest_agent = MorningDigestAgent(assistant=assistant, voice=voice_engine)

    return assistant, voice_engine, cloud, research_agent, digest_agent


# ── Commands ──────────────────────────────────────────────────────

@click.group()
def cli():
    """Javris Personal Intelligence System."""


@cli.command()
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--voice/--no-voice", default=False, help="Enable voice engine")
def serve(host, port, voice):
    """Start web server, dashboard, and autonomy engine."""
    banner()

    async def _serve():
        import uvicorn
        from core.config import get_config
        from server.app import app, set_dependencies

        cfg = get_config()
        assistant, voice_engine, cloud, research_agent, digest_agent = await _init_all(voice)
        set_dependencies(assistant, voice_engine, cloud, research_agent, digest_agent)

        h = host or cfg.javris_host
        p = port or cfg.javris_port

        console.print(f"\n[bold green]Javris running at[/bold green] [cyan]http://{h}:{p}[/cyan]")
        console.print(f"[dim]Owner: {assistant.personality.owner_name} | Model: {cfg.javris_claude_model}[/dim]")
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")

        config = uvicorn.Config(app=app, host=h, port=p, log_level="warning", timeout_keep_alive=300)
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            await assistant.close()

    asyncio.run(_serve())


@cli.command()
def chat():
    """Interactive terminal chat."""
    banner()

    async def _chat():
        assistant, _, _, _, _ = await _init_all(False)
        name = assistant.personality.owner_name
        console.print(f"[dim]Hello, {name}. Type 'quit' to exit, '/new' for new session.[/dim]\n")

        # Start autonomy in background
        assistant.start_autonomy()

        try:
            while True:
                user_input = Prompt.ask(f"[bold cyan]{name}[/bold cyan]")
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                if user_input == "/new":
                    assistant.new_session()
                    console.print("[dim]New session.[/dim]")
                    continue
                if not user_input.strip():
                    continue

                console.print("[dim]…[/dim]")
                reply = await assistant.chat(user_input)
                console.print("\n[bold green]Javris[/bold green]")
                console.print(Markdown(reply))
                console.print()
        except KeyboardInterrupt:
            pass
        finally:
            await assistant.close()
            console.print("\n[dim]Goodbye.[/dim]")

    asyncio.run(_chat())


@cli.command()
def voice():
    """Continuous voice mode — say the wake word to activate."""
    banner()

    async def _voice():
        from core.config import get_config
        cfg = get_config()
        assistant, voice_engine, _, _, _ = await _init_all(True)
        name = assistant.personality.owner_name
        console.print(f"[dim]Voice mode active. Say '{cfg.wake_word}' to talk to Javris.[/dim]")
        console.print("[dim]Tip: Javris uses streaming — first words are spoken as they arrive.[/dim]")
        assistant.start_autonomy()

        async def handle(text: str):
            console.print(f"[cyan]{name}:[/cyan] {text}")
            full_reply = ""
            sentence_buf = ""
            speak_tasks = []

            def _is_sentence_end(buf: str) -> bool:
                """True when buf ends at a natural spoken break."""
                b = buf.rstrip()
                if len(b) < 20:          # too short to bother
                    return False
                if b[-1] in "!?":        # always break on ! ?
                    return True
                # Break on ". " followed by more or end
                if b.endswith(".") and len(b) >= 30:
                    return True
                if len(b) >= 120:        # safety valve for run-on
                    return True
                return False

            try:
                async for chunk in assistant.voice_stream(text):
                    full_reply += chunk
                    sentence_buf += chunk
                    if _is_sentence_end(sentence_buf):
                        utterance = sentence_buf.strip()
                        sentence_buf = ""
                        t = asyncio.create_task(voice_engine.speak(utterance))
                        speak_tasks.append(t)

                # Speak any remaining text
                leftover = sentence_buf.strip()
                if leftover:
                    speak_tasks.append(asyncio.create_task(voice_engine.speak(leftover)))

                if speak_tasks:
                    await asyncio.gather(*speak_tasks, return_exceptions=True)

            except Exception as e:
                logger.error(f"Voice handle error: {e}")
                await voice_engine.speak("Sorry, I ran into a problem. Please try again.")
                full_reply = full_reply or "Error"

            console.print(f"[green]Javris:[/green] {full_reply[:300]}")

        try:
            await voice_engine.interactive_loop(handle)
        except KeyboardInterrupt:
            pass
        finally:
            await assistant.close()

    asyncio.run(_voice())


@cli.command()
@click.option("--location", default="", help="City for weather")
@click.option("--speak/--no-speak", default=False)
def digest(location, speak):
    """Run morning digest."""
    banner()
    async def _run():
        assistant, voice_engine, _, _, digest_agent = await _init_all(speak)
        result = await digest_agent.run(location=location, speak=speak)
        console.print(Markdown(result.get("digest_text", str(result))))
        await assistant.close()
    asyncio.run(_run())


@cli.command()
@click.argument("topic")
@click.option("--depth", default=3)
def research(topic, depth):
    """Deep multi-source research."""
    banner()
    async def _run():
        from rich.progress import Progress, SpinnerColumn, TextColumn
        assistant, _, _, research_agent, _ = await _init_all(False)

        with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), transient=True) as p:
            t = p.add_task("Researching…", total=None)
            async def prog(step): p.update(t, description=step)
            result = await research_agent.research(topic, depth=depth, on_progress=prog)

        console.print(Markdown(result.get("full_report") or result.get("summary", "")))
        await assistant.close()
    asyncio.run(_run())


@cli.command()
def setup():
    """First-run wizard to personalise Javris."""
    banner()
    from core.personality import get_personality

    console.print("[bold]Welcome! Let's set up your personal Javris.[/bold]\n")
    p = get_personality()

    name = Prompt.ask("Your name", default=p.owner_name)
    location = Prompt.ask("Your city (for weather)", default=p.preferred_weather_location or "")
    tone = Prompt.ask("Tone [conversational/concise/formal/witty]", default=p.tone)
    domains_raw = Prompt.ask("Interests (comma-separated)", default=", ".join(p.domains))
    wake = Prompt.ask("Morning briefing hour (0-23)", default=str(p.wake_hour))
    speak = Confirm.ask("Speak proactive alerts aloud?", default=p.speak_proactively)

    p.update(
        owner_name=name,
        preferred_weather_location=location,
        tone=tone,
        domains=[d.strip() for d in domains_raw.split(",") if d.strip()],
        wake_hour=int(wake),
        speak_proactively=speak,
    )
    console.print(f"\n[green]✓ Javris configured for {name}.[/green]")
    console.print("Run [cyan]python main.py serve[/cyan] to start.")


@cli.command()
@click.option("--camera", default=0, type=int, help="Camera device index")
@click.option("--no-preview", is_flag=True, default=False, help="Hide camera preview window")
@click.option("--with-assistant/--no-assistant", default=False, help="Connect to Javris assistant core")
@click.option("--list-gestures", is_flag=True, default=False, help="List all configured gesture mappings and exit")
def gesture(camera, no_preview, with_assistant, list_gestures):
    """Real-time gesture control — touchless OS control via hand gestures."""
    banner()

    if list_gestures:
        from gesture import GestureMapper
        from rich.table import Table
        mapper = GestureMapper()
        table = Table(title="Configured Gesture Mappings", show_lines=True)
        table.add_column("Gesture", style="cyan", no_wrap=True)
        table.add_column("Action", style="green")
        table.add_column("Description", style="dim")
        for m in mapper.list_mappings():
            table.add_row(m["gesture"], m["action"], m["description"])
        console.print(table)
        return

    async def _run():
        from gesture import GestureController

        controller = GestureController(
            camera_id=camera,
            show_preview=not no_preview,
        )

        if with_assistant:
            assistant, voice_engine, _, _, _ = await _init_all(False)
            controller.set_assistant(assistant)
            controller.set_voice_engine(voice_engine)
            controller.set_autonomy(assistant.autonomy)
            console.print("[dim]Gesture control connected to Javris assistant[/dim]")

        console.print("[bold cyan]Gesture control active.[/bold cyan]")
        console.print("[dim]Show your hand to the camera.  Press 'q' in preview or Ctrl+C to stop.[/dim]\n")

        try:
            await controller.run_async()
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()
            console.print("\n[dim]Gesture control stopped.[/dim]")

    asyncio.run(_run())


@cli.command("live")
@click.option("--mode", default="audio", type=click.Choice(["audio", "video"]), help="audio = voice only, video = voice + webcam")
@click.option("--voice-name", default="Puck", type=click.Choice(["Puck", "Charon", "Kore", "Fenrir", "Aoede"]), help="Gemini voice")
def live(mode, voice_name):
    """Gemini Live — real-time audio/video conversation (no STT/TTS pipeline)."""
    banner()
    from core.personality import get_personality

    p = get_personality()
    system = (
        f"You are Jarvis, a brilliant and concise AI assistant serving {p.owner_name}. "
        "Respond naturally and conversationally. Keep answers brief unless asked to elaborate."
    )

    console.print(f"[bold cyan]Gemini Live[/bold cyan] | mode=[yellow]{mode}[/yellow] voice=[yellow]{voice_name}[/yellow]")
    if mode == "video":
        console.print("[dim]Webcam will be opened — Gemini can see your screen/environment.[/dim]")
    console.print("[dim]Press Ctrl-C to end the session.[/dim]\n")

    async def _run():
        from core.gemini_live import start_live_session
        await start_live_session(mode=mode, voice=voice_name, system_prompt=system)

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
