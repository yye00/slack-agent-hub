"""Tests for thread-based task dispatch (ISSUES.md #3)."""
import pytest

from core.thread_dispatch import is_thread_reply, build_background_prompt


def test_is_thread_reply_true():
    """A message with thread_ts different from its own ts is a thread reply."""
    event = {"thread_ts": "1234.5678", "ts": "1234.9999"}
    assert is_thread_reply(event) is True


def test_is_thread_reply_false_no_thread():
    """A message without thread_ts is not a thread reply."""
    event = {"ts": "1234.5678"}
    assert is_thread_reply(event) is False


def test_is_thread_reply_false_parent():
    """A message where thread_ts == ts is the thread parent, not a reply."""
    event = {"thread_ts": "1234.5678", "ts": "1234.5678"}
    assert is_thread_reply(event) is False


def test_build_background_prompt():
    """Background prompt wraps user text with /btw instruction."""
    result = build_background_prompt("fix the typo in README", backend_name="claude")
    assert "/btw" in result
    assert "fix the typo in README" in result


def test_build_background_prompt_unknown_backend():
    """Unknown backends get a plain prompt with a background note."""
    result = build_background_prompt("do something", backend_name="gemini")
    assert "do something" in result
    assert "background" in result.lower()
