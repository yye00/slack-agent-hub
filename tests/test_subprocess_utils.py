"""Tests for shared subprocess utilities."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backends.subprocess_utils import run_cli_query, build_env


def test_build_env_inherits_path():
    env = build_env()
    assert "PATH" in env


def test_build_env_merges_extras():
    env = build_env({"GEMINI_API_KEY": "test-key"})
    assert env["GEMINI_API_KEY"] == "test-key"
    assert "PATH" in env


def test_build_env_preserves_home():
    env = build_env()
    assert "HOME" in env


@pytest.mark.asyncio
async def test_run_cli_query_collects_stdout_lines():
    """run_cli_query yields each stdout line as bytes."""
    lines = []
    async for line in run_cli_query(["echo", '{"type":"text"}\n{"type":"done"}']):
        lines.append(line)
    assert len(lines) >= 1


@pytest.mark.asyncio
async def test_run_cli_query_raises_on_bad_command():
    """Non-existent command raises an error."""
    with pytest.raises(FileNotFoundError):
        async for _ in run_cli_query(["/nonexistent/binary"]):
            pass


@pytest.mark.asyncio
async def test_run_cli_query_timeout():
    """Process exceeding timeout is killed."""
    with pytest.raises(asyncio.TimeoutError):
        async for _ in run_cli_query(["sleep", "60"], timeout=0.1):
            pass
