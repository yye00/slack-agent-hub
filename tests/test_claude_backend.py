import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backends.claude import ClaudeBackend
from backends.base import Event, CommandInfo


def test_claude_backend_name():
    backend = ClaudeBackend()
    assert backend.name == "claude"


def test_claude_capabilities():
    backend = ClaudeBackend()
    caps = backend.capabilities()
    assert "session_resume" in caps
    assert "compact" in caps
    assert "cost_tracking" in caps


def test_claude_supported_commands():
    backend = ClaudeBackend()
    cmds = backend.supported_commands()
    names = [c.name for c in cmds]
    assert "/compact" in names
    assert "/model" in names
    assert "/cost" in names


def test_claude_terminal_resume_command():
    backend = ClaudeBackend()
    cmd = backend.terminal_resume_command("cc4e3ea8")
    assert cmd == "claude --resume cc4e3ea8"
