import pytest
from core.commands import parse_message, ParsedCommand, MessageType


def test_parse_hub_command():
    result = parse_message("!status fred")
    assert result.type == MessageType.COMMAND
    assert result.command == "status"
    assert result.args == ["fred"]


def test_parse_hub_command_no_args():
    result = parse_message("!agents")
    assert result.type == MessageType.COMMAND
    assert result.command == "agents"
    assert result.args == []


def test_parse_new_session_with_label_and_model():
    result = parse_message("!new hotfix --model claude-opus-4-6")
    assert result.type == MessageType.COMMAND
    assert result.command == "new"
    assert "hotfix" in result.args
    assert result.options.get("model") == "claude-opus-4-6"


def test_parse_cli_passthrough():
    result = parse_message("> /compact")
    assert result.type == MessageType.CLI_PASSTHROUGH
    assert result.cli_command == "/compact"


def test_parse_cli_passthrough_with_args():
    result = parse_message("> /model claude-opus-4-6")
    assert result.type == MessageType.CLI_PASSTHROUGH
    assert result.cli_command == "/model claude-opus-4-6"


def test_parse_handoff():
    result = parse_message("@Bob@host2: Here is the handoff context")
    assert result.type == MessageType.HANDOFF
    assert result.handoff_target == "bob"
    assert result.handoff_host == "host2"
    assert "handoff context" in result.handoff_content


def test_parse_direct_address():
    result = parse_message("Fred, check the logs")
    assert result.type == MessageType.PLAIN_TEXT
    assert result.text == "Fred, check the logs"


def test_parse_plain_text():
    result = parse_message("what files are in this directory?")
    assert result.type == MessageType.PLAIN_TEXT
    assert result.text == "what files are in this directory?"


def test_parse_broadcast():
    result = parse_message("Everyone: git pull")
    assert result.type == MessageType.BROADCAST
    assert "git pull" in result.text


def test_parse_watch_command():
    result = parse_message("!watch /var/log/app.log every 30s")
    assert result.type == MessageType.COMMAND
    assert result.command == "watch"
    assert "/var/log/app.log" in result.args


def test_parse_schedule_command():
    result = parse_message('!schedule fred "run tests" every 6h')
    assert result.type == MessageType.COMMAND
    assert result.command == "schedule"


def test_parse_pin_command():
    result = parse_message("!pin Always use Poetry, not pip")
    assert result.type == MessageType.COMMAND
    assert result.command == "pin"
    assert result.args == ["Always", "use", "Poetry,", "not", "pip"]
