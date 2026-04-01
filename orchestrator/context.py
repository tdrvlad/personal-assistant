import os


def assemble(
    history: list[dict],
    language: str,
    user_name: str = "Vlad",
    documents_dir: str = "/documents",
    interface: str = "voice",
) -> str:
    parts = []

    parts.append(f"""[SYSTEM CONTEXT]
Interface: {interface}
User: {user_name}
Language: {language}
Documents directory: {documents_dir}""")

    if history:
        parts.append("[CONVERSATION HISTORY]")
        parts.append(format_history(history[:-1]))  # all but the current message

    parts.append(get_language_instruction(language))
    parts.append(get_interface_instruction(interface))

    # The current user message is the last entry in history
    if history:
        current = history[-1]
        if current["role"] == "user":
            parts.append(f"[CURRENT MESSAGE]\nUser: {current['content']}")

    return "\n\n".join(p for p in parts if p)


def format_history(history: list[dict]) -> str:
    lines = []
    for msg in history:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def get_language_instruction(language: str) -> str:
    if language == "ro":
        return "Răspunde în română."
    return "Respond in English."


def get_interface_instruction(interface: str) -> str:
    if interface == "voice":
        return (
            "VOICE RESPONSE RULES: "
            "1-3 sentences maximum. "
            "No markdown, no asterisks, no bullet points, no headers. "
            "Plain spoken language only. "
            "If listing items, speak naturally: 'You have three things: eggs, milk, and bread.'"
        )
    return (
        "TELEGRAM RESPONSE RULES: "
        "Be concise but can use light formatting. "
        "Up to a few paragraphs if needed."
    )
