import pytest
import tempfile
import os
from pathlib import Path

from core.config import load_config, HubConfig, AgentConfig, ProfileConfig


@pytest.fixture
def minimal_config_file(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("""
host_id: host1
host_name: "test-machine"

backends:
  claude:
    module: backends.claude
    default_model: claude-sonnet-4-5

agents:
  fred:
    backend: claude
    model: claude-sonnet-4-5
    channels: ["#test-channel"]
    cwd: /tmp/test-project
    profile: dev

ops_channel: "#ops"
registry_channel: "#agent-registry"

profiles:
  dev:
    allowed_tools: [Read, Write, Edit, Bash, LS, Grep, Glob]
    permission_mode: acceptEdits

heartbeat:
  interval_secs: 15
  tips: true
  stall_warn_mins: 5

monitors:
  default_poll_secs: 30

transcript:
  lookback_days: 7
  onboarding: true

permissions:
  admin_users: []
  ops_users: []
  commands: {}
""")
    return config


def test_load_config_returns_hub_config(minimal_config_file):
    cfg = load_config(minimal_config_file)
    assert isinstance(cfg, HubConfig)
    assert cfg.host_id == "host1"
    assert cfg.host_name == "test-machine"


def test_load_config_parses_agents(minimal_config_file):
    cfg = load_config(minimal_config_file)
    assert "fred" in cfg.agents
    agent = cfg.agents["fred"]
    assert isinstance(agent, AgentConfig)
    assert agent.backend == "claude"
    assert agent.model == "claude-sonnet-4-5"
    assert agent.channels == ["#test-channel"]
    assert agent.cwd == "/tmp/test-project"
    assert agent.profile == "dev"


def test_load_config_parses_profiles(minimal_config_file):
    cfg = load_config(minimal_config_file)
    assert "dev" in cfg.profiles
    profile = cfg.profiles["dev"]
    assert isinstance(profile, ProfileConfig)
    assert "Bash" in profile.allowed_tools
    assert profile.permission_mode == "acceptEdits"


def test_load_config_parses_backends(minimal_config_file):
    cfg = load_config(minimal_config_file)
    assert "claude" in cfg.backends
    assert cfg.backends["claude"]["module"] == "backends.claude"
    assert cfg.backends["claude"]["default_model"] == "claude-sonnet-4-5"


def test_load_config_validates_agent_backend_exists(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("""
host_id: host1
host_name: test
backends: {}
agents:
  fred:
    backend: nonexistent
    model: x
    channels: ["#c"]
    cwd: /tmp
    profile: dev
ops_channel: "#ops"
registry_channel: "#agent-registry"
profiles:
  dev:
    allowed_tools: [Read]
    permission_mode: default
heartbeat:
  interval_secs: 15
  tips: true
  stall_warn_mins: 5
monitors:
  default_poll_secs: 30
transcript:
  lookback_days: 7
  onboarding: true
permissions:
  admin_users: []
  ops_users: []
  commands: {}
""")
    with pytest.raises(ValueError, match="nonexistent"):
        load_config(config)


def test_load_config_validates_agent_profile_exists(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("""
host_id: host1
host_name: test
backends:
  claude:
    module: backends.claude
    default_model: x
agents:
  fred:
    backend: claude
    model: x
    channels: ["#c"]
    cwd: /tmp
    profile: nonexistent
ops_channel: "#ops"
registry_channel: "#agent-registry"
profiles:
  dev:
    allowed_tools: [Read]
    permission_mode: default
heartbeat:
  interval_secs: 15
  tips: true
  stall_warn_mins: 5
monitors:
  default_poll_secs: 30
transcript:
  lookback_days: 7
  onboarding: true
permissions:
  admin_users: []
  ops_users: []
  commands: {}
""")
    with pytest.raises(ValueError, match="nonexistent"):
        load_config(config)


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.yaml"))
