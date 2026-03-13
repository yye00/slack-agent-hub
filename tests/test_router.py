import pytest
from core.router import Router, RouteResult, RouteAction
from core.commands import MessageType


@pytest.fixture
def router():
    channel_agents = {
        "C_SPE": ["fred", "bob"],
        "C_INFRA": ["dana"],
    }
    agent_hosts = {
        "fred": "host1",
        "bob": "host2",
        "dana": "host1",
    }
    return Router(
        ops_channel_id="C_OPS",
        channel_agents=channel_agents,
        agent_hosts=agent_hosts,
        local_agents={"fred", "dana"},
    )


def test_route_command_in_ops_channel(router):
    result = router.route("!status fred", "C_OPS", "U_USER")
    assert result.action == RouteAction.COMMAND
    assert result.parsed.command == "status"


def test_route_plain_text_in_ops_channel_ignored(router):
    result = router.route("hello there", "C_OPS", "U_USER")
    assert result.action == RouteAction.IGNORE


def test_route_plain_text_to_default_agent(router):
    result = router.route("check the logs", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "fred"


def test_route_direct_address_to_named_agent(router):
    result = router.route("Bob, check the tests", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "bob"


def test_route_direct_address_case_insensitive(router):
    result = router.route("bob, check the tests", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "bob"


def test_route_cli_passthrough_to_default_agent(router):
    result = router.route("> /compact", "C_SPE", "U_USER")
    assert result.action == RouteAction.CLI_PASSTHROUGH
    assert result.target_agent == "fred"


def test_route_broadcast(router):
    result = router.route("Everyone: git pull", "C_SPE", "U_USER")
    assert result.action == RouteAction.BROADCAST
    assert set(result.broadcast_agents) == {"fred", "bob"}


def test_route_handoff_local_agent(router):
    result = router.route("@Dana@host1: here's the work", "C_SPE", "U_USER")
    assert result.action == RouteAction.HANDOFF_LOCAL
    assert result.target_agent == "dana"


def test_route_handoff_remote_agent(router):
    result = router.route("@Bob@host2: here's the work", "C_SPE", "U_USER")
    assert result.action == RouteAction.HANDOFF_REMOTE


def test_route_unknown_channel_ignored(router):
    result = router.route("hello", "C_UNKNOWN", "U_USER")
    assert result.action == RouteAction.IGNORE


def test_route_command_in_project_channel(router):
    result = router.route("!sessions", "C_SPE", "U_USER")
    assert result.action == RouteAction.COMMAND
    assert result.target_agent == "fred"
