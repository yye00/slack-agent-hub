import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from core.agent import Agent
from core.config import AgentConfig, ProfileConfig
from storage.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def agent_config():
    return AgentConfig(
        backend="claude",
        model="claude-sonnet-4-5",
        channels=["#test"],
        cwd="/tmp/test",
        profile="dev",
    )


@pytest.fixture
def profile():
    return ProfileConfig(
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        permission_mode="acceptEdits",
    )


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.name = "claude"
    backend.terminal_resume_command.return_value = "claude --resume abc"
    backend.capabilities.return_value = {"session_resume"}
    return backend


def test_agent_identity(agent_config, profile, mock_backend):
    agent = Agent(
        name="fred",
        host_id="host1",
        config=agent_config,
        profile=profile,
        backend=mock_backend,
        db=MagicMock(),
    )
    assert agent.name == "fred"
    assert agent.host_id == "host1"
    assert agent.display_name == "Fred@host1"


def test_agent_status_default(agent_config, profile, mock_backend):
    agent = Agent(
        name="fred",
        host_id="host1",
        config=agent_config,
        profile=profile,
        backend=mock_backend,
        db=MagicMock(),
    )
    assert agent.status == "active"


def test_agent_pause_unpause(agent_config, profile, mock_backend):
    agent = Agent(
        name="fred",
        host_id="host1",
        config=agent_config,
        profile=profile,
        backend=mock_backend,
        db=MagicMock(),
    )
    agent.pause()
    assert agent.status == "paused"
    agent.unpause()
    assert agent.status == "active"


def test_agent_system_prompt(agent_config, profile, mock_backend):
    agent = Agent(
        name="fred",
        host_id="host1",
        config=agent_config,
        profile=profile,
        backend=mock_backend,
        db=MagicMock(),
    )
    prompt = agent.build_system_prompt(roster_text="No other agents online")
    assert "Fred" in prompt
    assert "host1" in prompt
    assert "/tmp/test" in prompt
    assert "No other agents online" in prompt


def test_agent_system_prompt_with_pins(agent_config, profile, mock_backend):
    agent = Agent(
        name="fred",
        host_id="host1",
        config=agent_config,
        profile=profile,
        backend=mock_backend,
        db=MagicMock(),
    )
    pins = ["Always use Poetry", "Run tests before committing"]
    prompt = agent.build_system_prompt(roster_text="", pins=pins)
    assert "Always use Poetry" in prompt
    assert "Run tests before committing" in prompt
