"""Slack message formatting, chunking, and sending."""

import re


def chunk_response(text: str, max_chars: int = 3800) -> list[str]:
    """Split a response into Slack-safe chunks at line boundaries.

    Preserves code blocks — if a chunk would split inside a fenced block,
    close it and re-open in the next chunk.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0
    in_code_block = False
    code_fence = ""

    for line in lines:
        line_len = len(line) + 1  # +1 for newline

        # Track code blocks
        fence_match = re.match(r"^(```\w*)", line)
        if fence_match:
            if not in_code_block:
                in_code_block = True
                code_fence = fence_match.group(1)
            else:
                in_code_block = False
                code_fence = ""

        if current_len + line_len > max_chars and current:
            # Close code block if we're in one
            chunk_text = "\n".join(current)
            if in_code_block:
                chunk_text += "\n```"
            chunks.append(chunk_text)

            # Start new chunk, re-open code block if needed
            current = []
            current_len = 0
            if in_code_block:
                current.append(code_fence)
                current_len = len(code_fence) + 1

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _format_elapsed(secs: int) -> str:
    """Format seconds as human-readable elapsed time."""
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    remaining_secs = secs % 60
    if mins < 60:
        return f"{mins}m{remaining_secs:02d}s"
    hours = mins // 60
    remaining_mins = mins % 60
    return f"{hours}h{remaining_mins:02d}m"


def _format_tokens(tokens: int | None) -> str:
    if tokens is None:
        return "--"
    if tokens >= 1000:
        return f"{tokens // 1000}k"
    return str(tokens)


def format_heartbeat(
    agent_name: str,
    host_id: str,
    backend_name: str,
    elapsed_secs: int,
    tool_count: int,
    last_tool: str,
    recent_tools: list[str],
    context_tokens: int | None,
    context_limit: int | None,
    tip: str | None,
    stalled: bool,
    stall_secs: int = 0,
) -> str:
    """Format the single living heartbeat message."""
    ctx = f"{_format_tokens(context_tokens)}/{_format_tokens(context_limit)} tokens"
    recent_str = " → ".join(recent_tools) if recent_tools else "--"

    if stalled:
        stall_time = _format_elapsed(stall_secs)
        return (
            f"⚠️ {agent_name}@{host_id} ({backend_name}) — no activity for {stall_time}\n"
            f"├─ {tool_count} tool calls │ last: {last_tool}\n"
            f"├─ May be reasoning deeply or stuck in a loop\n"
            f"├─ Context: {ctx}\n"
            f"└─ Use !cancel to stop, or wait it out"
        )

    elapsed = _format_elapsed(elapsed_secs)
    lines = [
        f"⏳ {agent_name}@{host_id} ({backend_name}) working… {elapsed}",
        f"├─ {tool_count} tool calls │ last: {last_tool}",
        f"├─ Recent: {recent_str}",
    ]
    if tip:
        lines.append(f"├─ Context: {ctx}")
        lines.append(f"└─ 💡 {tip}")
    else:
        lines.append(f"└─ Context: {ctx}")

    return "\n".join(lines)


def format_completion(
    agent_name: str,
    host_id: str,
    backend_name: str,
    elapsed_secs: int,
    tool_counts: dict[str, int],
    context_tokens: int | None,
    context_limit: int | None,
    session_id: str,
    terminal_resume_cmd: str,
) -> str:
    """Format the completion message (replaces heartbeat on finish)."""
    elapsed = _format_elapsed(elapsed_secs)
    tools_str = ", ".join(f"{k}: {v}" for k, v in tool_counts.items())
    total = sum(tool_counts.values())
    ctx = f"{_format_tokens(context_tokens)}/{_format_tokens(context_limit)} tokens"

    return (
        f"✅ {agent_name}@{host_id} ({backend_name}) finished in {elapsed}\n"
        f"├─ {total} tool calls │ {tools_str}\n"
        f"├─ Context: {ctx}\n"
        f"└─ Session {session_id} │ resume in terminal: {terminal_resume_cmd}"
    )
