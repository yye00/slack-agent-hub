"""Per-user permission enforcement for hub commands and actions."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import PermissionsConfig


class PermLevel(IntEnum):
    USER = 0
    OPS = 1
    ADMIN = 2


# Default required level per command.  Everything not listed defaults to USER.
DEFAULT_COMMAND_PERMS: dict[str, PermLevel] = {
    # ADMIN only
    "reload": PermLevel.ADMIN,
    "audit": PermLevel.ADMIN,
    # OPS and above
    "restart": PermLevel.OPS,
    "pause": PermLevel.OPS,
    "unpause": PermLevel.OPS,
    "cancel": PermLevel.OPS,
    "test": PermLevel.OPS,
    "diag": PermLevel.OPS,
    "logs": PermLevel.OPS,
    "health": PermLevel.OPS,
}


class PermissionChecker:
    """Enforces per-user permission levels.

    Safe default: when *both* ``admin_users`` and ``ops_users`` are empty in
    the config, all checks pass — the hub behaves as if permissions are
    disabled.  This avoids locking out operators on a freshly-configured hub.
    """

    def __init__(self, cfg: "PermissionsConfig"):
        self._admin_users: frozenset[str] = frozenset(cfg.admin_users or [])
        self._ops_users: frozenset[str] = frozenset(cfg.ops_users or [])
        # Merge default perms with any overrides from config.commands
        self._command_perms: dict[str, PermLevel] = dict(DEFAULT_COMMAND_PERMS)
        for cmd, level_str in (cfg.commands or {}).items():
            try:
                self._command_perms[cmd] = PermLevel[level_str.upper()]
            except KeyError:
                pass  # ignore invalid level names

        # If neither list is configured, disable enforcement entirely.
        self._enforcement_enabled: bool = bool(
            self._admin_users or self._ops_users
        )

    # ── Public helpers ────────────────────────────────────────────────────────

    def get_level(self, user_id: str) -> PermLevel:
        if user_id in self._admin_users:
            return PermLevel.ADMIN
        if user_id in self._ops_users:
            return PermLevel.OPS
        return PermLevel.USER

    def check_command(self, user_id: str, command: str) -> bool:
        """Return True if *user_id* may execute *command*."""
        if not self._enforcement_enabled:
            return True
        required = self._command_perms.get(command, PermLevel.USER)
        return self.get_level(user_id) >= required

    def check_cli_passthrough(self, user_id: str) -> bool:
        """CLI passthrough requires OPS level."""
        if not self._enforcement_enabled:
            return True
        return self.get_level(user_id) >= PermLevel.OPS

    def check_agent_query(self, user_id: str) -> bool:
        """Agent queries are always allowed (USER level)."""
        return True

    def denial_message(self, user_id: str, command: str) -> str:
        level = self.get_level(user_id)
        return (
            f"⛔ Permission denied for `!{command}`. "
            f"Your level: {level.name}"
        )

    def cli_denial_message(self, user_id: str) -> str:
        level = self.get_level(user_id)
        return (
            f"⛔ Permission denied for CLI passthrough. "
            f"Your level: {level.name}"
        )
