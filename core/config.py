"""Configuration loading and validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProfileConfig:
    allowed_tools: list[str]
    permission_mode: str = "default"


@dataclass
class AgentConfig:
    backend: str
    model: str
    channels: list[str]
    cwd: str
    profile: str


@dataclass
class HeartbeatConfig:
    interval_secs: int = 15
    tips: bool = True
    stall_warn_mins: int = 5


@dataclass
class MonitorConfig:
    default_poll_secs: int = 30


@dataclass
class TranscriptConfig:
    lookback_days: int = 7
    onboarding: bool = True


@dataclass
class PermissionsConfig:
    admin_users: list[str] = field(default_factory=list)
    ops_users: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)


@dataclass
class HubConfig:
    host_id: str
    host_name: str
    backends: dict[str, dict[str, Any]]
    agents: dict[str, AgentConfig]
    profiles: dict[str, ProfileConfig]
    ops_channel: str
    registry_channel: str
    heartbeat: HeartbeatConfig
    monitors: MonitorConfig
    transcript: TranscriptConfig
    permissions: PermissionsConfig


def load_config(path: Path) -> HubConfig:
    """Load and validate config from YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    profiles = {
        name: ProfileConfig(**pdata) for name, pdata in raw["profiles"].items()
    }

    agents = {}
    for name, adata in raw.get("agents", {}).items():
        if adata["backend"] not in raw.get("backends", {}):
            raise ValueError(
                f"Agent '{name}' references backend '{adata['backend']}' "
                f"which is not defined in backends"
            )
        if adata["profile"] not in profiles:
            raise ValueError(
                f"Agent '{name}' references profile '{adata['profile']}' "
                f"which is not defined in profiles"
            )
        agents[name] = AgentConfig(**adata)

    hb_raw = raw.get("heartbeat", {})
    mon_raw = raw.get("monitors", {})
    tr_raw = raw.get("transcript", {})
    perm_raw = raw.get("permissions", {})

    return HubConfig(
        host_id=raw["host_id"],
        host_name=raw["host_name"],
        backends=raw.get("backends", {}),
        agents=agents,
        profiles=profiles,
        ops_channel=raw["ops_channel"],
        registry_channel=raw["registry_channel"],
        heartbeat=HeartbeatConfig(**hb_raw),
        monitors=MonitorConfig(**mon_raw),
        transcript=TranscriptConfig(**tr_raw),
        permissions=PermissionsConfig(**perm_raw),
    )
