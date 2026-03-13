"""Per-agent memory file management."""

from pathlib import Path


def read_memory(cwd: str) -> str:
    """Read MEMORY.md from agent's working directory."""
    mem_file = Path(cwd) / ".claude-memory" / "MEMORY.md"
    if not mem_file.exists():
        return ""
    return mem_file.read_text()


def append_memory(cwd: str, content: str):
    """Append to MEMORY.md, creating dirs if needed."""
    mem_dir = Path(cwd) / ".claude-memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    mem_file = mem_dir / "MEMORY.md"
    with open(mem_file, "a") as f:
        f.write(content + "\n")


def clear_memory(cwd: str):
    """Clear MEMORY.md contents."""
    mem_file = Path(cwd) / ".claude-memory" / "MEMORY.md"
    if mem_file.exists():
        mem_file.write_text("")


def truncate_to_token_limit(text: str, max_tokens: int = 3000) -> str:
    """Truncate text to approximate token limit (~4 chars per token)."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
