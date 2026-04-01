import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "/documents")

# Import after logging is configured
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, CLINotFoundError, CLIConnectionError
from system_prompt import build as build_system_prompt
from tools.memory_tools import create_memory_mcp_server

app = FastAPI(title="Pi Assistant Agent")

memory_server = create_memory_mcp_server()


class AgentRequest(BaseModel):
    prompt: str
    language: str = "en"


class AgentResponse(BaseModel):
    text: str
    error: str | None = None


@app.post("/run", response_model=AgentResponse)
async def run_agent(request: AgentRequest) -> AgentResponse:
    logger.info("Running agent (lang=%s), prompt length=%d", request.language, len(request.prompt))
    try:
        text = await _run_query(request.prompt, request.language)
        return AgentResponse(text=text)
    except Exception as e:
        logger.error("Agent error: %s", e, exc_info=True)
        return AgentResponse(text="", error=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _run_query(prompt: str, language: str) -> str:
    system_prompt = build_system_prompt(language)
    result_text = ""

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "WebSearch"],
            cwd=DOCUMENTS_DIR,
            permission_mode="acceptEdits",
            max_turns=10,
            mcp_servers={"memory": memory_server},
        ),
    ):
        if isinstance(message, ResultMessage):
            result_text = message.result
            break

    if not result_text:
        logger.warning("Agent returned no result text")
        return (
            "Sorry, I couldn't come up with a response."
            if language != "ro"
            else "Îmi pare rău, nu am putut formula un răspuns."
        )

    return result_text


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=LOG_LEVEL.lower())
