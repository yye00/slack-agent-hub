import pytest
from backends.base import Event, SessionInfo, Backend, CommandInfo


def test_event_creation():
    e = Event(type="text", content="hello", detail="", raw={})
    assert e.type == "text"
    assert e.content == "hello"


def test_session_info_creation():
    info = SessionInfo(
        session_id="abc123",
        input_tokens=1000,
        output_tokens=500,
        model="claude-sonnet-4-5",
        context_limit=128000,
    )
    assert info.input_tokens == 1000
    assert info.context_limit == 128000


def test_session_info_defaults():
    info = SessionInfo(session_id="abc123")
    assert info.input_tokens is None
    assert info.output_tokens is None
    assert info.context_limit is None


def test_command_info_creation():
    cmd = CommandInfo(name="/compact", description="Compact context", backend="claude")
    assert cmd.name == "/compact"


def test_backend_is_abstract():
    with pytest.raises(TypeError):
        Backend()  # Can't instantiate abstract class
