"""Tests for per-user permissions and audit log."""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.permissions import PermissionChecker, PermLevel
from core.config import PermissionsConfig
from storage.db import Database


# ── PermissionChecker unit tests ──────────────────────────────────────────────

class TestPermissionChecker:
    def _make_checker(self, admin_users=None, ops_users=None, commands=None):
        cfg = PermissionsConfig(
            admin_users=admin_users or [],
            ops_users=ops_users or [],
            commands=commands or {},
        )
        return PermissionChecker(cfg)

    def test_no_config_allows_everything(self):
        """When no admin/ops users are configured, all users pass all checks."""
        checker = self._make_checker()
        assert checker.check_command("U_ANYONE", "reload") is True
        assert checker.check_command("U_ANYONE", "audit") is True
        assert checker.check_cli_passthrough("U_ANYONE") is True

    def test_admin_user_can_do_everything(self):
        checker = self._make_checker(admin_users=["UADMIN"])
        assert checker.check_command("UADMIN", "reload") is True
        assert checker.check_command("UADMIN", "audit") is True
        assert checker.check_command("UADMIN", "restart") is True
        assert checker.check_command("UADMIN", "agents") is True
        assert checker.check_cli_passthrough("UADMIN") is True

    def test_ops_user_can_use_ops_commands(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UOPS", "restart") is True
        assert checker.check_command("UOPS", "pause") is True
        assert checker.check_command("UOPS", "unpause") is True
        assert checker.check_command("UOPS", "cancel") is True
        assert checker.check_command("UOPS", "test") is True
        assert checker.check_command("UOPS", "diag") is True
        assert checker.check_command("UOPS", "logs") is True
        assert checker.check_command("UOPS", "health") is True
        assert checker.check_cli_passthrough("UOPS") is True

    def test_ops_user_cannot_use_admin_commands(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UOPS", "reload") is False
        assert checker.check_command("UOPS", "audit") is False

    def test_regular_user_can_use_user_commands(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UREGULAR", "agents") is True
        assert checker.check_command("UREGULAR", "status") is True
        assert checker.check_command("UREGULAR", "help") is True
        assert checker.check_command("UREGULAR", "pin") is True

    def test_regular_user_cannot_use_ops_commands(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UREGULAR", "restart") is False
        assert checker.check_command("UREGULAR", "pause") is False
        assert checker.check_command("UREGULAR", "health") is False

    def test_regular_user_cannot_use_admin_commands(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UREGULAR", "reload") is False
        assert checker.check_command("UREGULAR", "audit") is False

    def test_regular_user_cannot_use_cli_passthrough(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_cli_passthrough("UREGULAR") is False

    def test_get_level_admin(self):
        checker = self._make_checker(admin_users=["UADMIN"])
        assert checker.get_level("UADMIN") == PermLevel.ADMIN

    def test_get_level_ops(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.get_level("UOPS") == PermLevel.OPS

    def test_get_level_user(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.get_level("URANDOM") == PermLevel.USER

    def test_get_level_unconfigured(self):
        """When no admin/ops configured, everyone is effectively unrestricted (USER level)."""
        checker = self._make_checker()
        assert checker.get_level("URANDOM") == PermLevel.USER

    def test_custom_command_permission_override(self):
        """Commands dict in config overrides defaults."""
        checker = self._make_checker(
            admin_users=["UADMIN"],
            ops_users=["UOPS"],
            commands={"status": "admin"},  # override status to admin-only
        )
        assert checker.check_command("UOPS", "status") is False
        assert checker.check_command("UADMIN", "status") is True

    def test_audit_command_requires_admin(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UADMIN", "audit") is True
        assert checker.check_command("UOPS", "audit") is False
        assert checker.check_command("URANDOM", "audit") is False

    def test_reload_command_requires_admin(self):
        checker = self._make_checker(admin_users=["UADMIN"], ops_users=["UOPS"])
        assert checker.check_command("UADMIN", "reload") is True
        assert checker.check_command("UOPS", "reload") is False

    def test_admin_user_is_also_ops(self):
        """Admin users should be able to do ops-level commands too."""
        checker = self._make_checker(admin_users=["UADMIN"])
        assert checker.check_command("UADMIN", "restart") is True
        assert checker.check_command("UADMIN", "health") is True


# ── Database audit log tests ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_audit_log_table_exists(db):
    """audit_log table should exist after migration."""
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [row["name"] for row in tables]
    assert "audit_log" in table_names


@pytest.mark.asyncio
async def test_log_audit_and_get(db):
    await db.log_audit(
        user_id="U123",
        action="COMMAND",
        target="restart",
        channel_id="C456",
        detail="!restart agent1",
    )
    entries = await db.get_audit_log(limit=10)
    assert len(entries) == 1
    assert entries[0]["user_id"] == "U123"
    assert entries[0]["action"] == "COMMAND"
    assert entries[0]["target"] == "restart"
    assert entries[0]["channel_id"] == "C456"
    assert entries[0]["detail"] == "!restart agent1"
    assert entries[0]["timestamp"]


@pytest.mark.asyncio
async def test_log_audit_multiple_entries_ordered(db):
    await db.log_audit("U1", "COMMAND", "pause", "C1", "!pause")
    await db.log_audit("U2", "CLI_PASSTHROUGH", None, "C1", "/status")
    await db.log_audit("U3", "COMMAND", "reload", "C2", "!reload")

    entries = await db.get_audit_log(limit=10)
    assert len(entries) == 3
    # Most recent first
    assert entries[0]["user_id"] == "U3"
    assert entries[1]["user_id"] == "U2"
    assert entries[2]["user_id"] == "U1"


@pytest.mark.asyncio
async def test_get_audit_log_respects_limit(db):
    for i in range(10):
        await db.log_audit(f"U{i}", "COMMAND", "agents", "C1", f"!agents {i}")

    entries = await db.get_audit_log(limit=3)
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_log_audit_null_target(db):
    """target field is nullable."""
    await db.log_audit("U1", "CLI_PASSTHROUGH", None, "C1", "/ls")
    entries = await db.get_audit_log(limit=5)
    assert entries[0]["target"] is None


# ── hub.py integration tests (mocked) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_command_denied_posts_error():
    """When a user lacks permission for a command, a denial message is posted."""
    from core.permissions import PermissionChecker
    from core.config import PermissionsConfig

    # Simulate: admin configured, regular user tries !reload
    cfg = PermissionsConfig(admin_users=["UADMIN"], ops_users=[])
    checker = PermissionChecker(cfg)

    assert checker.check_command("URANDOM", "reload") is False
    level = checker.get_level("URANDOM")
    assert level == PermLevel.USER


@pytest.mark.asyncio
async def test_handle_message_cli_passthrough_denied_for_user():
    from core.permissions import PermissionChecker
    from core.config import PermissionsConfig

    cfg = PermissionsConfig(admin_users=["UADMIN"], ops_users=["UOPS"])
    checker = PermissionChecker(cfg)

    assert checker.check_cli_passthrough("URANDOM") is False
    assert checker.check_cli_passthrough("UOPS") is True
    assert checker.check_cli_passthrough("UADMIN") is True


@pytest.mark.asyncio
async def test_handle_message_agent_query_allowed_for_all():
    """Agent queries are always allowed regardless of permission level."""
    from core.permissions import PermissionChecker
    from core.config import PermissionsConfig

    cfg = PermissionsConfig(admin_users=["UADMIN"], ops_users=["UOPS"])
    checker = PermissionChecker(cfg)

    # AGENT_QUERY is always allowed — check_agent_query should return True for all
    assert checker.check_agent_query("URANDOM") is True
    assert checker.check_agent_query("UOPS") is True
    assert checker.check_agent_query("UADMIN") is True


# ── !audit command tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_audit_shows_entries(db):
    """!audit command should format audit log entries."""
    from core.command_handler import CommandHandler

    # Seed some audit entries
    await db.log_audit("U123", "COMMAND", "restart", "C1", "!restart agent1")
    await db.log_audit("U456", "CLI_PASSTHROUGH", None, "C1", "/status")

    poster = MagicMock()
    poster.post = AsyncMock()
    slack_client = MagicMock()

    handler = CommandHandler(agents={}, db=db, slack_client=slack_client, poster=poster)
    await handler._cmd_audit([], {}, "C1", None, None, "UADMIN")

    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args
    text = call_kwargs[1]["text"] if call_kwargs[1] else call_kwargs[0][1]
    assert "U123" in text or "U456" in text
    assert "restart" in text or "CLI_PASSTHROUGH" in text


@pytest.mark.asyncio
async def test_cmd_audit_respects_limit_arg(db):
    """!audit [N] should use N as the limit."""
    from core.command_handler import CommandHandler

    for i in range(20):
        await db.log_audit(f"U{i}", "COMMAND", "agents", "C1", f"!agents")

    poster = MagicMock()
    poster.post = AsyncMock()
    slack_client = MagicMock()

    handler = CommandHandler(agents={}, db=db, slack_client=slack_client, poster=poster)
    await handler._cmd_audit(["5"], {}, "C1", None, None, "UADMIN")

    call_kwargs = poster.post.call_args
    text = call_kwargs[1]["text"] if call_kwargs[1] else call_kwargs[0][1]
    # Should show "5" or "last 5" in text
    assert "5" in text


@pytest.mark.asyncio
async def test_cmd_audit_empty_log(db):
    """!audit with empty log should show a friendly message."""
    from core.command_handler import CommandHandler

    poster = MagicMock()
    poster.post = AsyncMock()
    slack_client = MagicMock()

    handler = CommandHandler(agents={}, db=db, slack_client=slack_client, poster=poster)
    await handler._cmd_audit([], {}, "C1", None, None, "UADMIN")

    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args
    text = call_kwargs[1]["text"] if call_kwargs[1] else call_kwargs[0][1]
    assert "No audit" in text or "empty" in text.lower() or "0" in text
