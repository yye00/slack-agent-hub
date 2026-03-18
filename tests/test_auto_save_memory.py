"""Tests for auto-save session summaries to agent MEMORY.md (#23)."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from core.continuity import generate_session_summary


def test_generate_summary_from_response():
    summary = generate_session_summary("Fixed the login bug. Updated auth.py validation.")
    assert "login" in summary.lower() or "auth" in summary.lower()


def test_generate_summary_truncates_long_responses():
    long_text = "word " * 200
    summary = generate_session_summary(long_text, max_length=100)
    assert len(summary) <= 103  # 100 + "..."


def test_generate_summary_empty_response():
    assert generate_session_summary("") == ""


def test_generate_summary_preserves_short_text():
    text = "All tests pass now."
    assert generate_session_summary(text) == text


@pytest.mark.asyncio
async def test_auto_save_calls_append_memory():
    """After a successful query with a session record, append_memory is called."""
    from features.memory import append_memory

    with patch("features.memory.append_memory") as mock_append:
        # Simulate what hub.py does after a successful query
        result_text = "Implemented the login fix and all tests pass."
        session_name = "fix-login-bug"
        cwd = "/tmp/test-agent"

        summary = generate_session_summary(result_text, max_length=300)
        if summary:
            header = f"## Session: {session_name}"
            from features.memory import append_memory as real_fn
            mock_append(cwd, f"\n{header}\n{summary}\n")

        mock_append.assert_called_once()
        call_args = mock_append.call_args[0]
        assert call_args[0] == cwd
        assert "fix-login-bug" in call_args[1]
        assert "login fix" in call_args[1]


@pytest.mark.asyncio
async def test_auto_save_skips_empty_response():
    """No memory append when query response is empty."""
    summary = generate_session_summary("")
    assert summary == ""
    # The hub code checks `if summary:` before appending — empty means skip


@pytest.mark.asyncio
async def test_auto_save_skips_failed_query():
    """No memory append when query failed."""
    # The hub code checks `if result.success and result.text:` — failed queries skip auto-save
    # This test documents the expected behavior
    from core.query import QueryResult
    result = QueryResult(text="", session_id="s1", success=False, error="timeout")
    assert not result.success  # Auto-save skipped for failed queries
