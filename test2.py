import asyncio
import uvicorn
from fastapi import FastAPI
app = FastAPI()

async def main():
    config = uvicorn.Config(app=app, host="127.0.0.1", port=8001, log_level="info")
    server = uvicorn.Server(config)
    print("Serving...")
    await server.serve()
    print("Done serving.")

asyncio.run(main())
