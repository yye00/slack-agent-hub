"""Message routing — determines which agent handles each message."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from core.commands import MessageType, ParsedCommand, parse_message


class RouteAction(Enum):
    COMMAND = auto()
    AGENT_QUERY = auto()
    CLI_PASSTHROUGH = auto()
    BROADCAST = auto()
    DISCUSS = auto()
    HANDOFF_LOCAL = auto()
    HANDOFF_REMOTE = auto()
    IGNORE = auto()


@dataclass
class RouteResult:
    action: RouteAction
    parsed: ParsedCommand
    target_agent: str = ""
    broadcast_agents: list[str] = field(default_factory=list)


class Router:
    def __init__(
        self,
        ops_channel_id: str,
        channel_agents: dict[str, list[str]],
        agent_hosts: dict[str, str],
        local_agents: set[str],
        local_host_id: str = "",
        display_names: dict[str, str] | None = None,
    ):
        self._ops_channel_id = ops_channel_id
        self._channel_agents = channel_agents
        self._agent_hosts = agent_hosts
        self._local_agents = local_agents
        self._local_host_id = local_host_id
        self._all_agent_names = {name.lower() for name in agent_hosts}
        # Build reverse lookup: display_name.lower() -> internal_name
        self._display_to_internal: dict[str, str] = {}
        if display_names:
            for internal, display in display_names.items():
                self._display_to_internal[display.lower()] = internal
                # Also index the internal name itself
                self._display_to_internal[internal.lower()] = internal

    def route(self, text: str, channel_id: str, user_id: str) -> RouteResult:
        parsed = parse_message(text)

        if channel_id == self._ops_channel_id:
            if parsed.type == MessageType.COMMAND:
                return RouteResult(action=RouteAction.COMMAND, parsed=parsed)
            return RouteResult(action=RouteAction.IGNORE, parsed=parsed)

        agents_in_channel = self._channel_agents.get(channel_id)
        if not agents_in_channel:
            return RouteResult(action=RouteAction.IGNORE, parsed=parsed)

        default_agent = agents_in_channel[0]

        if parsed.type == MessageType.COMMAND:
            return RouteResult(action=RouteAction.COMMAND, parsed=parsed, target_agent=default_agent)

        if parsed.type == MessageType.CLI_PASSTHROUGH:
            return RouteResult(action=RouteAction.CLI_PASSTHROUGH, parsed=parsed, target_agent=default_agent)

        if parsed.type == MessageType.HANDOFF:
            target = parsed.handoff_target  # already lowercased
            # Resolve display name to internal name
            resolved = self._display_to_internal.get(target, target)
            if resolved in self._local_agents:
                return RouteResult(action=RouteAction.HANDOFF_LOCAL, parsed=parsed, target_agent=resolved)
            return RouteResult(action=RouteAction.HANDOFF_REMOTE, parsed=parsed)

        if parsed.type == MessageType.DISCUSS:
            return RouteResult(action=RouteAction.DISCUSS, parsed=parsed, broadcast_agents=list(agents_in_channel))

        if parsed.type == MessageType.BROADCAST:
            return RouteResult(action=RouteAction.BROADCAST, parsed=parsed, broadcast_agents=list(agents_in_channel))

        if parsed.type == MessageType.PLAIN_TEXT:
            agent_name, should_ignore = self._detect_direct_address(parsed.text, agents_in_channel)
            if should_ignore:
                return RouteResult(action=RouteAction.IGNORE, parsed=parsed)
            if agent_name:
                return RouteResult(action=RouteAction.AGENT_QUERY, parsed=parsed, target_agent=agent_name)
            if self._is_multi_host_channel(channel_id):
                return RouteResult(action=RouteAction.IGNORE, parsed=parsed)
            return RouteResult(action=RouteAction.AGENT_QUERY, parsed=parsed, target_agent=default_agent)

        return RouteResult(action=RouteAction.IGNORE, parsed=parsed)

    def _is_multi_host_channel(self, channel_id: str) -> bool:
        agents = self._channel_agents.get(channel_id, [])
        hosts = {self._agent_hosts.get(a, "") for a in agents}
        return len(hosts) > 1

    def _resolve_name(self, name: str) -> str | None:
        """Resolve an internal name or display name to the internal agent name."""
        low = name.lower()
        if low in self._display_to_internal:
            return self._display_to_internal[low]
        if low in self._all_agent_names:
            return low
        return None

    def _detect_direct_address(self, text: str, channel_agents: list[str]) -> tuple[str | None, bool]:
        # Check name@host format first (e.g. "Ziggy@fedora:" or "debater@fedora:")
        m = re.match(r"^(\w+)@([\w-]+)[,:\s]", text, re.IGNORECASE)
        if m:
            raw_name = m.group(1)
            host = m.group(2)
            resolved = self._resolve_name(raw_name)
            if resolved:
                if host == self._local_host_id and resolved in self._local_agents:
                    return (resolved, False)
                return (None, True)

        # Check plain name format — match internal names AND display names
        # Build list of (pattern, internal_name) to check
        local_channel = set(channel_agents) & self._local_agents
        names_to_check: list[tuple[str, str]] = []
        for agent_name in local_channel:
            names_to_check.append((agent_name, agent_name))
        # Add display name aliases
        for display_low, internal in self._display_to_internal.items():
            if internal in local_channel:
                names_to_check.append((display_low, internal))

        for match_name, internal_name in names_to_check:
            pattern = re.compile(rf"^@?{re.escape(match_name)}[,:\s]", re.IGNORECASE)
            if pattern.match(text):
                return (internal_name, False)
        return (None, False)

    def get_channel_agents(self, channel_id: str) -> list[str]:
        return self._channel_agents.get(channel_id, [])
