"""Session continuity — save summaries and inject preambles on restart."""

from __future__ import annotations


def build_resume_preamble(
    previous_session_name: str,
    summary: str,
    ended_cleanly: bool,
) -> str:
    """Build a preamble to inject when resuming work after a session ends."""
    parts = [
        "You are resuming work.",
        f"Previous session: {previous_session_name}",
    ]

    if not ended_cleanly:
        parts.append(
            "WARNING: The previous session ended uncleanly (crash or timeout). "
            "Please verify the current state of your work before continuing."
        )

    if summary:
        parts.append(f"Previous session summary: {summary}")
    else:
        parts.append("No summary available from the previous session.")

    return "\n".join(parts)


def generate_session_summary(last_response: str, max_length: int = 500) -> str:
    """Generate a simple session summary from the last response.

    This is a lightweight summary — just the last response truncated.
    A more sophisticated version could use the backend to generate a real summary.
    """
    if not last_response:
        return ""
    # Take the first max_length chars as a rough summary
    text = last_response.strip()
    if len(text) > max_length:
        text = text[:max_length].rsplit(" ", 1)[0] + "..."
    return text
