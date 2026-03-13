from slack_io.messages import chunk_response, format_heartbeat, format_completion


def test_chunk_response_short_message():
    """Messages under 3800 chars return as single chunk."""
    text = "Hello world"
    chunks = chunk_response(text)
    assert chunks == ["Hello world"]


def test_chunk_response_long_message():
    """Messages over 3800 chars are split at newlines."""
    text = ("Line of text\n") * 400  # ~5200 chars
    chunks = chunk_response(text)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 3800


def test_chunk_response_preserves_code_blocks():
    """Code blocks should not be split mid-block."""
    text = "Before\n```python\n" + "x = 1\n" * 500 + "```\nAfter"
    chunks = chunk_response(text)
    # Each chunk should have balanced ``` markers or none
    for chunk in chunks:
        assert chunk.count("```") % 2 == 0


def test_format_heartbeat_active():
    hb = format_heartbeat(
        agent_name="Fred",
        host_id="host1",
        backend_name="claude",
        elapsed_secs=758,
        tool_count=23,
        last_tool="Edit lib/parser.py:142",
        recent_tools=["Read", "Grep", "Edit", "Bash(pytest)", "Edit"],
        context_tokens=34000,
        context_limit=128000,
        tip="Use > /compact to free up context",
        stalled=False,
    )
    assert "Fred@host1" in hb
    assert "claude" in hb
    assert "12m" in hb
    assert "23 tool calls" in hb
    assert "Edit lib/parser.py:142" in hb
    assert "34k/128k" in hb
    assert "/compact" in hb


def test_format_heartbeat_stalled():
    hb = format_heartbeat(
        agent_name="Fred",
        host_id="host1",
        backend_name="claude",
        elapsed_secs=900,
        tool_count=23,
        last_tool="Bash(pytest)",
        recent_tools=["Bash(pytest)"],
        context_tokens=34000,
        context_limit=128000,
        tip=None,
        stalled=True,
        stall_secs=312,
    )
    assert "no activity" in hb.lower() or "⚠️" in hb
    assert "!cancel" in hb


def test_format_heartbeat_no_tip():
    hb = format_heartbeat(
        agent_name="Fred",
        host_id="host1",
        backend_name="claude",
        elapsed_secs=120,
        tool_count=5,
        last_tool="Read config.py",
        recent_tools=["Read"],
        context_tokens=10000,
        context_limit=128000,
        tip=None,
        stalled=False,
    )
    assert "Fred@host1" in hb
    assert "10k/128k" in hb
    # Should end with context line, no tip line
    assert "💡" not in hb
    assert hb.count("```") == 0  # no broken formatting


def test_format_completion():
    msg = format_completion(
        agent_name="Fred",
        host_id="host1",
        backend_name="claude",
        elapsed_secs=862,
        tool_counts={"Read": 12, "Edit": 8, "Bash": 15, "Grep": 7, "Other": 5},
        context_tokens=52000,
        context_limit=128000,
        session_id="cc4e3ea8",
        terminal_resume_cmd="claude --resume cc4e3ea8",
    )
    assert "finished" in msg.lower() or "✅" in msg
    assert "cc4e3ea8" in msg
    assert "14m" in msg
    assert "Read: 12" in msg
