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
    ):
        self._ops_channel_id = ops_channel_id
        self._channel_agents = channel_agents
        self._agent_hosts = agent_hosts
        self._local_agents = local_agents
        self._all_agent_names = {name.lower() for name in agent_hosts}

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
            target = parsed.handoff_target
            if target in self._local_agents:
                return RouteResult(action=RouteAction.HANDOFF_LOCAL, parsed=parsed, target_agent=target)
            return RouteResult(action=RouteAction.HANDOFF_REMOTE, parsed=parsed)

        if parsed.type == MessageType.BROADCAST:
            return RouteResult(action=RouteAction.BROADCAST, parsed=parsed, broadcast_agents=list(agents_in_channel))

        if parsed.type == MessageType.PLAIN_TEXT:
            addressed = self._detect_direct_address(parsed.text, agents_in_channel)
            if addressed:
                return RouteResult(action=RouteAction.AGENT_QUERY, parsed=parsed, target_agent=addressed)
            return RouteResult(action=RouteAction.AGENT_QUERY, parsed=parsed, target_agent=default_agent)

        return RouteResult(action=RouteAction.IGNORE, parsed=parsed)

    def _detect_direct_address(self, text: str, channel_agents: list[str]) -> str | None:
        for agent_name in channel_agents:
            pattern = re.compile(rf"^{re.escape(agent_name)}[,:\s]", re.IGNORECASE)
            if pattern.match(text):
                return agent_name
        return None
