import asyncio
import logging
import os
import time
from enum import Enum

import httpx

from context import assemble

logger = logging.getLogger(__name__)

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000")
USER_NAME = os.getenv("USER_NAME", "Vlad")
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "/documents")


class SessionState(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    HOT = "hot"


class AgentError(Exception):
    pass


class SessionManager:
    HOT_DURATION_SEC = 30
    HISTORY_WINDOW = 20

    def __init__(self):
        self.state = SessionState.IDLE
        self.history: list[dict] = []
        self.hot_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def handle_turn(self, text: str, language: str) -> dict:
        async with self._lock:
            if not text.strip():
                return self._error_response("Sorry, I didn't catch that. Could you say it again?", language)

            self.history.append({"role": "user", "content": text})
            self.state = SessionState.PROCESSING

            try:
                prompt = assemble(
                    history=self.history,
                    language=language,
                    user_name=USER_NAME,
                    documents_dir=DOCUMENTS_DIR,
                    interface="voice",
                )
                response_text = await self._call_agent(prompt, language)
            except AgentError as e:
                logger.error("Agent call failed: %s", e)
                self.history.pop()  # remove the user turn we just added
                self.state = SessionState.IDLE
                return self._error_response(
                    "Sorry, I'm having trouble connecting. Please try again." if language != "ro"
                    else "Îmi pare rău, am probleme de conexiune. Te rog încearcă din nou.",
                    language,
                )

            self.history.append({"role": "assistant", "content": response_text})
            self._trim_history()

            self.state = SessionState.HOT
            self.hot_expires_at = time.monotonic() + self.HOT_DURATION_SEC

            return {
                "text_to_speak": response_text,
                "language": language,
                "hot_session": True,
                "hot_duration_sec": self.HOT_DURATION_SEC,
            }

    def is_hot(self) -> bool:
        return self.state == SessionState.HOT and time.monotonic() < self.hot_expires_at

    def expire_hot_session(self):
        if self.state == SessionState.HOT:
            self.state = SessionState.IDLE
            self.history.clear()
            logger.info("Hot session expired, history cleared")

    async def _call_agent(self, prompt: str, language: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{AGENT_URL}/run",
                    json={"prompt": prompt, "language": language},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raise AgentError(data["error"])
                return data["text"]
        except httpx.HTTPError as e:
            raise AgentError(str(e)) from e

    def _trim_history(self):
        if len(self.history) > self.HISTORY_WINDOW:
            self.history = self.history[-self.HISTORY_WINDOW:]

    def _error_response(self, message: str, language: str) -> dict:
        return {
            "text_to_speak": message,
            "language": language,
            "hot_session": False,
            "hot_duration_sec": 0,
        }
