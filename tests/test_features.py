import pytest
import pytest_asyncio
import tempfile
from pathlib import Path

from features.memory import read_memory, append_memory, clear_memory, truncate_to_token_limit


def test_read_memory_missing_file(tmp_path):
    result = read_memory(str(tmp_path / "nonexistent"))
    assert result == ""


def test_read_memory_existing(tmp_path):
    mem_dir = tmp_path / ".claude-memory"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text("## Session 1\n- Did something\n")
    result = read_memory(str(tmp_path))
    assert "Did something" in result


def test_append_memory(tmp_path):
    append_memory(str(tmp_path), "New memory entry")
    mem_file = tmp_path / ".claude-memory" / "MEMORY.md"
    assert mem_file.exists()
    assert "New memory entry" in mem_file.read_text()


def test_clear_memory(tmp_path):
    append_memory(str(tmp_path), "Entry")
    clear_memory(str(tmp_path))
    result = read_memory(str(tmp_path))
    assert result == ""


def test_truncate_to_token_limit():
    long_text = "word " * 10000  # ~50000 chars
    truncated = truncate_to_token_limit(long_text, max_tokens=3000)
    # ~4 chars per token heuristic = 12000 chars max
    assert len(truncated) <= 12001


def test_truncate_short_text():
    short = "hello world"
    result = truncate_to_token_limit(short, max_tokens=3000)
    assert result == short


# ── Transcript tests ──

from features.transcript import summarize_for_onboarding


def test_summarize_for_onboarding_formats_messages():
    messages = [
        {"user": "U123", "text": "hello world"},
        {"user": "U456", "text": "nice work"},
    ]
    result = summarize_for_onboarding(messages)
    assert "<@U123>: hello world" in result
    assert "<@U456>: nice work" in result


def test_summarize_for_onboarding_truncates():
    messages = [{"user": "U1", "text": "x" * 5000}] * 5
    result = summarize_for_onboarding(messages, max_chars=8000)
    assert len(result) <= 8020  # allow for truncation marker
    assert "[truncated]" in result


# ── Permalinks tests ──

import re
from features.permalinks import PERMALINK_RE


def test_permalink_regex_matches():
    url = "https://myteam.slack.com/archives/C1234567/p1710340920123456"
    m = PERMALINK_RE.search(url)
    assert m is not None
    assert m.group(1) == "C1234567"
    assert m.group(2) == "1710340920"
    assert m.group(3) == "123456"


def test_permalink_regex_no_match():
    assert PERMALINK_RE.search("https://google.com") is None


# ── Files tests ──

from features.files import extract_file_paths


def test_extract_file_paths_finds_paths(tmp_path):
    # Create a temp file to find
    test_file = tmp_path / "result.txt"
    test_file.write_text("hello")
    text = f"Output written to {test_file}"
    paths = extract_file_paths(text)
    assert str(test_file) in paths


def test_extract_file_paths_skips_system_dirs():
    text = "Check /etc/passwd and /proc/cpuinfo"
    paths = extract_file_paths(text)
    assert len(paths) == 0
