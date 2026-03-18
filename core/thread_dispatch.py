"""Thread-based task dispatch — routes threaded replies to background tasks."""

from __future__ import annotations


def is_thread_reply(event: dict) -> bool:
    """Check if a Slack event is a reply within a thread (not the parent)."""
    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    return bool(thread_ts and ts and thread_ts != ts)


# Backend-specific background task command prefixes
_BACKGROUND_COMMANDS = {
    "claude": "/btw",
}


def build_background_prompt(text: str, backend_name: str) -> str:
    """Wrap user text as a background task prompt for the given backend.

    For Claude, this uses /btw to dispatch a background task that won't
    pollute the main session context.
    """
    command = _BACKGROUND_COMMANDS.get(backend_name)
    if command:
        return f"{command} {text}"
    return f"[Background task] {text}"
