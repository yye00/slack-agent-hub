"""Tests for hub health monitoring (ISSUES.md #9)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_agent(name="agent1", host_id="testhost", status="active",
               session_id=None, query_task=None, backend_name="claude"):
    """Build a minimal mock Agent."""
    agent = MagicMock()
    agent.name = name
    agent.host_id = host_id
    agent.status = status
    agent.current_session_id = session_id
    agent._active_query_task = query_task
    agent.display_name = f"{name.capitalize()}@{host_id}"
    agent.backend = MagicMock()
    agent.backend.name = backend_name
    return agent


@pytest.mark.asyncio
async def test_periodic_health_heartbeat_to_ops():
    """Hub posts periodic health heartbeats to ops channel."""
    from core.health import HealthMonitor

    poster = MagicMock()
    poster.post = AsyncMock()
    agents = {"agent1": make_agent()}

    monitor = HealthMonitor(
        agents=agents,
        poster=poster,
        ops_channel_id="C_OPS",
        host_id="testhost",
        interval_secs=0,  # fire immediately
    )
    monitor.start()
    # Let the loop fire once
    await asyncio.sleep(0.05)
    monitor.stop()

    # Should have posted the health report
    assert poster.post.called
    call_kwargs = poster.post.call_args_list[-1].kwargs
    assert call_kwargs["channel"] == "C_OPS"
    assert "Hub health" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_health_report_includes_agent_count():
    """Health report includes number of active agents."""
    from core.health import build_health_report

    agents = {
        "a": make_agent("a", status="active"),
        "b": make_agent("b", status="paused"),
        "c": make_agent("c", status="active"),
    }
    report = build_health_report(agents, "myhost")

    assert "2 active" in report
    assert "1 paused" in report
    assert "3 total" in report


@pytest.mark.asyncio
async def test_health_report_includes_queries_in_flight():
    """Health report includes number of queries currently running."""
    from core.health import build_health_report

    running_task = MagicMock()
    running_task.done.return_value = False

    done_task = MagicMock()
    done_task.done.return_value = True

    agents = {
        "a": make_agent("a", query_task=running_task),
        "b": make_agent("b", query_task=done_task),
        "c": make_agent("c", query_task=None),
    }
    report = build_health_report(agents, "myhost")

    assert "Queries in flight: 1" in report


@pytest.mark.asyncio
async def test_health_report_includes_backend_connectivity():
    """Health report includes backend name for each agent."""
    from core.health import build_health_report

    agents = {"a": make_agent("a", backend_name="claude")}
    report = build_health_report(agents, "myhost")

    assert "claude" in report


@pytest.mark.asyncio
async def test_alert_on_agent_crash():
    """An alert is posted when a query task crashes with an exception."""
    from core.health import check_anomalies

    crashed_task = MagicMock()
    crashed_task.done.return_value = True
    crashed_task.cancelled.return_value = False
    crashed_task.exception.return_value = RuntimeError("boom")

    agents = {"a": make_agent("a", query_task=crashed_task)}
    alerts = check_anomalies(agents)

    assert any("crashed" in a for a in alerts)
    assert any("boom" in a for a in alerts)


@pytest.mark.asyncio
async def test_alert_on_backend_unreachable():
    """An alert is posted when an agent has an unknown/offline status."""
    from core.health import check_anomalies

    agents = {"a": make_agent("a", status="offline")}
    alerts = check_anomalies(agents)

    assert any("offline" in a for a in alerts)


@pytest.mark.asyncio
async def test_alert_on_query_timeout():
    """No crash alert for cancelled tasks (timeouts are typically cancellations)."""
    from core.health import check_anomalies

    cancelled_task = MagicMock()
    cancelled_task.done.return_value = True
    cancelled_task.cancelled.return_value = True  # cancelled, not crashed

    agents = {"a": make_agent("a", query_task=cancelled_task)}
    alerts = check_anomalies(agents)

    # Cancelled tasks should NOT produce a crash alert
    assert not any("crashed" in a for a in alerts)


@pytest.mark.asyncio
async def test_health_command():
    """!health returns an on-demand health summary."""
    from core.command_handler import CommandHandler

    poster = MagicMock()
    poster.post = AsyncMock()

    agent = make_agent("agent1", host_id="testhost")
    agents = {"agent1": agent}

    handler = CommandHandler(
        agents=agents,
        db=MagicMock(),
        slack_client=MagicMock(),
        poster=poster,
    )

    await handler.handle(
        command="health",
        args=[],
        options={},
        channel_id="C123",
        thread_ts=None,
        target_agent="agent1",
        user="U1",
    )

    poster.post.assert_called_once()
    text = poster.post.call_args.kwargs["text"]
    assert "Hub health" in text
    assert "testhost" in text
