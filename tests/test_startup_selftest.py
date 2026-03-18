"""Tests for startup self-test (ISSUES.md #6, incorporating #4)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.selftest import StartupSelfTest, CheckResult


@pytest.fixture
def slack_client():
    client = AsyncMock()
    client.auth_test = AsyncMock(return_value={"ok": True, "user": "bot", "team": "test"})
    client.conversations_info = AsyncMock(return_value={"ok": True, "channel": {"id": "C_OPS", "name": "ops"}})
    client.files_getUploadURLExternal = AsyncMock(return_value={"ok": True})
    return client


@pytest.fixture
def poster():
    p = AsyncMock()
    p.post = AsyncMock(return_value={"ts": "1234.5678"})
    return p


@pytest.mark.asyncio
async def test_selftest_checks_slack_api(slack_client, poster):
    """Self-test verifies Slack API connectivity."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=[])
    api_check = next(r for r in results if r.name == "slack_api")
    assert api_check.passed is True


@pytest.mark.asyncio
async def test_selftest_slack_api_failure(slack_client, poster):
    """Self-test detects Slack API failure."""
    slack_client.auth_test = AsyncMock(side_effect=Exception("connection refused"))
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=[])
    api_check = next(r for r in results if r.name == "slack_api")
    assert api_check.passed is False
    assert api_check.critical is True


@pytest.mark.asyncio
async def test_selftest_checks_ops_channel_writable(slack_client, poster):
    """Self-test verifies ops channel is accessible."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=[])
    ops_check = next(r for r in results if r.name == "ops_channel")
    assert ops_check.passed is True


@pytest.mark.asyncio
async def test_selftest_checks_channels_exist(slack_client, poster):
    """Self-test verifies configured channels exist."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=["C_SPE", "C_INFRA"], backend_names=[])
    channel_checks = [r for r in results if r.name.startswith("channel:")]
    assert len(channel_checks) == 2
    assert all(c.passed for c in channel_checks)


@pytest.mark.asyncio
async def test_selftest_channel_not_found(slack_client, poster):
    """Self-test detects when a channel doesn't exist."""
    slack_client.conversations_info = AsyncMock(side_effect=Exception("channel_not_found"))
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=["C_MISSING"], backend_names=[])
    ch_check = next(r for r in results if r.name == "channel:C_MISSING")
    assert ch_check.passed is False


@pytest.mark.asyncio
async def test_selftest_checks_backend_reachable(slack_client, poster):
    """Self-test verifies backend CLI is reachable."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=["claude"])
    be_check = next(r for r in results if r.name == "backend:claude")
    assert be_check.name == "backend:claude"
    assert be_check.critical is True


@pytest.mark.asyncio
async def test_selftest_posts_results_to_ops(slack_client, poster):
    """Self-test posts results summary to ops channel."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    await st.run_and_report(channel_ids=[], backend_names=[])
    poster.post.assert_called()
    text = poster.post.call_args[1]["text"]
    assert "self-test" in text.lower() or "Self-test" in text or "startup" in text.lower()


@pytest.mark.asyncio
async def test_selftest_returns_critical_failure_flag(slack_client, poster):
    """run_and_report returns False if any critical check failed."""
    slack_client.auth_test = AsyncMock(side_effect=Exception("down"))
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    ok = await st.run_and_report(channel_ids=[], backend_names=[])
    assert ok is False


@pytest.mark.asyncio
async def test_selftest_returns_true_on_all_pass(slack_client, poster):
    """run_and_report returns True when all checks pass."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    ok = await st.run_and_report(channel_ids=[], backend_names=[])
    assert ok is True


@pytest.mark.asyncio
async def test_selftest_checks_files_write_scope(slack_client, poster):
    """Self-test checks for files:write scope (Issue #4)."""
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=[])
    fw_check = next(r for r in results if r.name == "files_write_scope")
    assert fw_check.passed is True


@pytest.mark.asyncio
async def test_selftest_files_write_scope_missing(slack_client, poster):
    """Self-test detects missing files:write scope."""
    slack_client.files_getUploadURLExternal = AsyncMock(
        side_effect=Exception("missing_scope")
    )
    st = StartupSelfTest(slack_client=slack_client, poster=poster, ops_channel_id="C_OPS")
    results = await st.run_checks(channel_ids=[], backend_names=[])
    fw_check = next(r for r in results if r.name == "files_write_scope")
    assert fw_check.passed is False
    assert fw_check.critical is False
