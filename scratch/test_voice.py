import asyncio
import os
from core.voice import VoiceEngine
from core.config import get_config

async def test():
    cfg = get_config()
    cfg.tts_engine = "edge_tts"
    v = VoiceEngine()
    await v.init()
    print("Synthesizing 'Hello Sir'...")
    await v.speak("Hello Sir, testing the voice engine.")
    print("Test complete.")

if __name__ == "__main__":
    asyncio.run(test())
