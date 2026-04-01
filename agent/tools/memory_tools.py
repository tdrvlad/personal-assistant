# Phase 1 stubs — real implementation in Phase 5
from claude_agent_sdk import tool, create_sdk_mcp_server


@tool(
    "remember",
    "Store a fact, preference, decision, or context note in long-term memory",
    {"content": str, "category": str, "tags": str},
)
async def remember(args: dict) -> dict:
    # Phase 1: no-op
    return {"content": [{"type": "text", "text": "Remembered."}]}


@tool(
    "forget",
    "Delete memories matching a search query — only use when the user explicitly asks to forget something",
    {"query": str},
)
async def forget(args: dict) -> dict:
    # Phase 1: no-op
    return {"content": [{"type": "text", "text": "Forgotten."}]}


def create_memory_mcp_server():
    return create_sdk_mcp_server("memory-tools", tools=[remember, forget])
