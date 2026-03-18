"""Structured JSON logging with rotating file handler."""

import json
import logging
import logging.handlers
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional


class JsonFormatter(logging.Formatter):
    """Format LogRecords as single-line JSON."""

    # All standard LogRecord attributes — excluded from "extra" fields
    STANDARD_FIELDS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        # Build the message (handles %-style formatting)
        record.message = record.getMessage()

        data: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Exception info
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            data["exception"] = record.exc_text

        # Stack info
        if record.stack_info:
            data["stack_info"] = self.formatStack(record.stack_info)

        # Extra fields — anything not in the standard set
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_FIELDS and not key.startswith("_"):
                data[key] = value

        return json.dumps(data, default=str)


def setup_logging(
    log_dir: str = "logs",
    json_stdout: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    level: str = "INFO",
) -> None:
    """Configure root logger with stdout + rotating file handlers.

    Args:
        log_dir: Directory for log files (hub.log will be created here).
        json_stdout: If True, stdout handler uses JSON format; otherwise plain text.
        max_bytes: Max size before rotation (default 10 MB).
        backup_count: Number of rotated backup files to keep (default 5).
        level: Root logging level (default INFO).
    """
    root = logging.getLogger()

    # Clear any existing handlers so we start clean
    root.handlers.clear()

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(numeric_level)

    # ── Stdout handler ──
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    if json_stdout:
        stdout_handler.setFormatter(JsonFormatter())
    else:
        stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stdout_handler)

    # ── Rotating file handler (always JSON) ──
    log_path = f"{log_dir}/hub.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)
