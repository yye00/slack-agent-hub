import pytest
from core.registry import format_registry_message, parse_registry_messages, build_roster_text


def test_format_registry_message():
    agents_info = [
        {"name": "fred", "backend": "claude", "model": "sonnet", "channels": ["#spe"], "status": "active"},
        {"name": "dana", "backend": "gemini", "model": "2.5-pro", "channels": ["#infra"], "status": "idle"},
    ]
    msg = format_registry_message("host1", agents_info)
    assert "host1" in msg
    assert "fred" in msg.lower() or "Fred" in msg
    assert "dana" in msg.lower() or "Dana" in msg
    assert "active" in msg
    assert "claude" in msg


def test_parse_registry_messages():
    messages = [
        {"text": "📡 host1 online │ last seen: 2026-03-13T14:22:00Z\nFred (claude sonnet) │ #spe │ active\nDana (gemini 2.5-pro) │ #infra │ idle"},
        {"text": "📡 host2 online │ last seen: 2026-03-13T14:22:00Z\nBob (codex o3) │ #spe │ active"},
    ]
    roster = parse_registry_messages(messages)
    assert len(roster) >= 3
    fred = next(a for a in roster if a["name"].lower() == "fred")
    assert fred["host"] == "host1"


def test_parse_registry_messages_malformed():
    """Malformed messages should be silently skipped."""
    messages = [
        {"text": "just some random text"},
        {"text": ""},
        {"text": "📡 host3 online │ last seen: 2026-03-13\nmalformed agent line"},
    ]
    roster = parse_registry_messages(messages)
    assert len(roster) == 0  # No valid agent entries


def test_build_roster_text():
    roster = [
        {"name": "Fred", "host": "host1", "backend": "claude", "model": "sonnet", "channels": "#spe", "status": "active"},
        {"name": "Bob", "host": "host2", "backend": "codex", "model": "o3", "channels": "#spe", "status": "active"},
    ]
    text = build_roster_text(roster, self_name="fred", self_host="host1")
    assert "Fred@host1 (you)" in text
    assert "Bob@host2" in text
