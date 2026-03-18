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
        local_host_id="host1",
    )


def test_route_command_in_ops_channel(router):
    result = router.route("!status fred", "C_OPS", "U_USER")
    assert result.action == RouteAction.COMMAND
    assert result.parsed.command == "status"


def test_route_plain_text_in_ops_channel_ignored(router):
    result = router.route("hello there", "C_OPS", "U_USER")
    assert result.action == RouteAction.IGNORE


def test_route_plain_text_to_default_agent(router):
    # C_INFRA is single-host (only dana@host1), so unaddressed text routes to default
    result = router.route("check the logs", "C_INFRA", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "dana"


def test_route_direct_address_to_named_agent(router):
    # fred is local, so plain-name addressing works
    result = router.route("fred, check the tests", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "fred"


def test_route_direct_address_case_insensitive(router):
    result = router.route("Fred, check the tests", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "fred"


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


# ── Multi-host deduplication tests ──


def test_route_direct_address_name_at_host_local(router):
    """fred@host1 in a multi-host channel routes to fred."""
    result = router.route("fred@host1, check logs", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "fred"


def test_route_direct_address_name_at_host_remote(router):
    """bob@host2 is remote — this host should ignore."""
    result = router.route("bob@host2, check logs", "C_SPE", "U_USER")
    assert result.action == RouteAction.IGNORE


def test_route_direct_address_name_at_host_case_insensitive(router):
    """Fred@host1 should match case-insensitively."""
    result = router.route("Fred@host1, check logs", "C_SPE", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "fred"


def test_route_unaddressed_multi_host_channel_ignored(router):
    """Unaddressed message in multi-host channel (C_SPE) should be ignored."""
    result = router.route("check the logs", "C_SPE", "U_USER")
    assert result.action == RouteAction.IGNORE


def test_route_unaddressed_single_host_channel_routes(router):
    """Unaddressed message in single-host channel (C_INFRA) routes normally."""
    result = router.route("check the logs", "C_INFRA", "U_USER")
    assert result.action == RouteAction.AGENT_QUERY
    assert result.target_agent == "dana"


def test_route_direct_address_remote_agent_plain_name_ignored(router):
    """Plain-name addressing of a remote agent (bob) should not match."""
    result = router.route("bob, check the tests", "C_SPE", "U_USER")
    # bob is remote, so plain-name doesn't match -> unaddressed in multi-host -> IGNORE
    assert result.action == RouteAction.IGNORE
