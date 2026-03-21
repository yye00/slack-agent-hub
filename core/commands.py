"""Unified command parser for all hub commands."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from enum import Enum, auto


class MessageType(Enum):
    COMMAND = auto()         # !command [args]
    CLI_PASSTHROUGH = auto() # > /command
    HANDOFF = auto()         # @Name@host: message
    BROADCAST = auto()       # Everyone: message
    DISCUSS = auto()         # Debate: topic  (multi-round discussion)
    PLAIN_TEXT = auto()      # Regular message to agent


@dataclass
class ParsedCommand:
    type: MessageType
    command: str = ""
    args: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)
    cli_command: str = ""
    handoff_target: str = ""
    handoff_host: str = ""
    handoff_content: str = ""
    text: str = ""


_COMMAND_RE = re.compile(r"^!(\w+)\s*(.*)", re.DOTALL)
_CLI_PASSTHROUGH_RE = re.compile(r"^>\s*(/\S.*)", re.DOTALL)
_HANDOFF_RE = re.compile(r"^@(\w+)@([\w-]+):\s*(.*)", re.DOTALL)
_BROADCAST_RE = re.compile(r"^(?:Everyone|All):\s*(.*)", re.IGNORECASE | re.DOTALL)
_DISCUSS_RE = re.compile(r"^(?:Debate|Discuss|Discussion):\s*(.*)", re.IGNORECASE | re.DOTALL)
_OPTION_RE = re.compile(r"--(\w+)\s+(\S+)")


def parse_message(text: str) -> ParsedCommand:
    """Parse a Slack message into a structured command."""
    text = html.unescape(text).strip()

    m = _CLI_PASSTHROUGH_RE.match(text)
    if m:
        return ParsedCommand(type=MessageType.CLI_PASSTHROUGH, cli_command=m.group(1).strip())

    m = _HANDOFF_RE.match(text)
    if m:
        return ParsedCommand(
            type=MessageType.HANDOFF,
            handoff_target=m.group(1).lower(),
            handoff_host=m.group(2),
            handoff_content=m.group(3).strip(),
        )

    m = _COMMAND_RE.match(text)
    if m:
        command = m.group(1).lower()
        rest = m.group(2).strip()
        options = {}
        for opt_match in _OPTION_RE.finditer(rest):
            options[opt_match.group(1)] = opt_match.group(2)
        args_str = _OPTION_RE.sub("", rest).strip()
        args = args_str.split() if args_str else []
        return ParsedCommand(type=MessageType.COMMAND, command=command, args=args, options=options)

    m = _DISCUSS_RE.match(text)
    if m:
        topic_text = m.group(1).strip()
        # Extract --rounds N option if present
        options = {}
        for opt_match in _OPTION_RE.finditer(topic_text):
            options[opt_match.group(1)] = opt_match.group(2)
        topic_text = _OPTION_RE.sub("", topic_text).strip()
        return ParsedCommand(type=MessageType.DISCUSS, text=topic_text, options=options)

    m = _BROADCAST_RE.match(text)
    if m:
        return ParsedCommand(type=MessageType.BROADCAST, text=m.group(1).strip())

    return ParsedCommand(type=MessageType.PLAIN_TEXT, text=text)
