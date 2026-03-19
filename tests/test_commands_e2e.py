"""End-to-end command handler tests with mocked Slack + DB."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.command_handler import CommandHandler
from core.agent import Agent


def make_mock_agent(name="tester", host_id="fedora", status="active",
                    session_id="abc12345-6789-0000-1111-222233334444",
                    backend_name="claude", model="claude-sonnet-4-5",
                    cwd="/tmp/test"):
    """Create a mock Agent with enough structure for command handler."""
    agent = MagicMock(spec=Agent)
    agent.name = name
    agent.host_id = host_id
    agent.status = status
    agent.display_name = f"{name.capitalize()}@{host_id}"
    agent.current_session_id = session_id
    agent.config = MagicMock()
    agent.config.model = model
    agent.config.cwd = cwd
    agent.config.profile = "ops"
    agent.config.channels = ["C_TEST"]
    agent.backend = MagicMock()
    agent.backend.name = backend_name
    agent.backend.terminal_resume_command.return_value = f"claude --resume {session_id}"
    agent.backend.get_session_info = AsyncMock(return_value=MagicMock(input_tokens=1000, context_limit=200000))
    agent.profile = MagicMock()
    agent.profile.allowed_tools = ["Read", "Write", "Bash"]
    return agent


def make_handler(agents_dict):
    """Create a CommandHandler with mocked dependencies."""
    db = AsyncMock()
    db.get_session.return_value = {"id": "abc12345", "name": "test-session", "agent_name": "tester",
                                    "created_at": "2026-03-19T12:00:00", "status": "active"}
    db.list_sessions.return_value = [
        {"id": "abc12345", "name": "session-1", "agent_name": "tester",
         "created_at": "2026-03-19T12:00:00", "status": "active"},
        {"id": "def67890", "name": "session-2", "agent_name": "tester",
         "created_at": "2026-03-18T12:00:00", "status": "rotated"},
    ]
    db.search_messages.return_value = [
        {"text": "hello world", "user_id": "U123", "ts": "1234567890.123456"},
        {"text": "roster of agents", "user_id": "U456", "ts": "1234567891.123456"},
    ]
    db.get_cost_summary.return_value = {"input_tokens": 50000, "output_tokens": 12000}
    db.get_session_summaries.return_value = []

    slack = AsyncMock()
    slack.conversations_history.return_value = {
        "messages": [
            {"user": "U123", "text": "hello there", "ts": "1234567890.0"},
            {"user": "U456", "text": "!status", "ts": "1234567891.0"},
        ]
    }

    poster = AsyncMock()
    poster.post.return_value = {"ts": "9999.9999"}

    handler = CommandHandler(agents=agents_dict, db=db, slack_client=slack, poster=poster)
    return handler, poster, db


async def run_command(handler, cmd, args=None, target="tester"):
    """Run a command and return the poster's post calls."""
    args = args or []
    await handler.handle(cmd, args, {}, "C_TEST", None, target, "U_USER")


async def test_all_commands():
    """Test every command handler returns a response."""
    tester = make_mock_agent("tester")
    bob = make_mock_agent("bob", session_id="bob11111-2222-3333-4444-555566667777")
    agents = {"tester": tester, "bob": bob}
    handler, poster, db = make_handler(agents)

    tests = [
        ("help", [], "should show help text"),
        ("agents", [], "should list agents"),
        ("status", [], "should show agent status"),
        ("status", ["bob"], "should show bob's status"),
        ("roster", [], "should show full roster"),
        ("cost", [], "should show cost"),
        ("cost", ["bob"], "should show bob's cost"),
        ("search", ["hello"], "should search messages"),
        ("search", [], "should show usage error"),
        ("cancel", [], "should cancel or show no active query"),
        ("pause", [], "should pause agent"),
        ("unpause", [], "should unpause agent"),
        ("pin", ["Always", "be", "concise"], "should pin context"),
        ("pins", [], "should list pins"),
        ("unpin", ["1"], "should unpin"),
        ("memory", [], "should show memory"),
        ("context", [], "should show context"),
        ("history", [], "should show history"),
        ("sessions", [], "should list sessions"),
        ("sessions", ["bob"], "should list bob's sessions"),
        ("export", ["abc12345"], "should export session"),
        ("fork", ["abc12345"], "should fork session"),
    ]

    all_pass = True
    for cmd, args, desc in tests:
        poster.reset_mock()
        try:
            await run_command(handler, cmd, args)
            calls = poster.post.call_args_list
            if not calls:
                print(f"  FAIL: !{cmd} {' '.join(args)} — no response posted ({desc})")
                all_pass = False
            else:
                # Get the text from the call
                text = calls[0].kwargs.get("text", calls[0].args[0] if calls[0].args else "?")
                text_preview = text[:80].replace("\n", " ")
                print(f"  OK: !{cmd} {' '.join(args)} -> \"{text_preview}...\"")
        except Exception as e:
            print(f"  ERROR: !{cmd} {' '.join(args)} -> {type(e).__name__}: {e}")
            all_pass = False

    # Test !test separately (it calls backend.query which is async generator)
    poster.reset_mock()
    from backends.base import Event
    async def mock_query(**kwargs):
        yield Event(type="text", content="Hello from test!")
        yield Event(type="complete", content="", detail="session123")
    tester.backend.query = mock_query
    try:
        await run_command(handler, "test", ["say", "hi"])
        calls = poster.post.call_args_list
        if calls:
            text = calls[0].kwargs.get("text", "?")[:80]
            print(f"  OK: !test say hi -> \"{text}...\"")
        else:
            print(f"  FAIL: !test say hi — no response")
            all_pass = False
    except Exception as e:
        print(f"  ERROR: !test say hi -> {type(e).__name__}: {e}")
        all_pass = False

    # Test unknown command
    poster.reset_mock()
    await run_command(handler, "nonexistent", [])
    calls = poster.post.call_args_list
    if calls:
        text = calls[0].kwargs.get("text", "?")
        if "Unknown command" in text:
            print(f"  OK: !nonexistent -> unknown command error")
        else:
            print(f"  WARN: !nonexistent -> unexpected response: {text[:60]}")
    else:
        print(f"  FAIL: !nonexistent — no error response")
        all_pass = False

    return all_pass


async def test_import_command():
    """Test !import specifically — it has complex logic."""
    tester = make_mock_agent("tester")
    agents = {"tester": tester}
    handler, poster, db = make_handler(agents)

    # Mock the resume_session to succeed
    tester.backend.resume_session = AsyncMock(return_value=True)

    poster.reset_mock()
    await run_command(handler, "import", ["abc12345"])
    calls = poster.post.call_args_list
    if calls:
        text = calls[0].kwargs.get("text", "?")[:100]
        print(f"  OK: !import abc12345 -> \"{text}\"")
        return True
    print(f"  FAIL: !import abc12345 — no response")
    return False


if __name__ == "__main__":
    print("=" * 60)
    print("E2E Command Handler Tests")
    print("=" * 60)

    all_pass = True

    print("\n--- All Commands ---")
    if not asyncio.run(test_all_commands()):
        all_pass = False

    print("\n--- Import Command ---")
    if not asyncio.run(test_import_command()):
        all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("ALL E2E TESTS PASSED")
    else:
        print("SOME E2E TESTS FAILED")
    print("=" * 60)
    sys.exit(0 if all_pass else 1)
