import logging
import os
import stat

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from session import SessionManager

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/pi-assistant/orchestrator.sock"

app = FastAPI(title="Pi Assistant Orchestrator")
session_manager = SessionManager()


class TranscriptionRequest(BaseModel):
    text: str
    language: str = "en"


class TranscriptionResponse(BaseModel):
    text_to_speak: str
    language: str
    hot_session: bool
    hot_duration_sec: int


@app.on_event("startup")
async def startup():
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    logger.info("Orchestrator starting up")


@app.post("/transcription", response_model=TranscriptionResponse)
async def handle_transcription(request: TranscriptionRequest) -> TranscriptionResponse:
    logger.info("Received transcription (lang=%s): %s", request.language, request.text[:80])
    result = await session_manager.handle_turn(request.text, request.language)
    return TranscriptionResponse(**result)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "session_state": session_manager.state.value,
        "hot_session": session_manager.is_hot(),
    }


def run():
    # Remove stale socket if present
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    config = uvicorn.Config(app, uds=SOCKET_PATH, log_level=LOG_LEVEL.lower())
    server = uvicorn.Server(config)

    import asyncio

    async def serve():
        await server.serve()
        # Make socket world-writable so host user (non-root) can connect
        if os.path.exists(SOCKET_PATH):
            os.chmod(SOCKET_PATH, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)

    asyncio.run(serve())


if __name__ == "__main__":
    run()
