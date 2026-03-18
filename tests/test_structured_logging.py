"""Tests for core/structured_logging.py — JSON formatter and log setup."""

import json
import logging
import logging.handlers
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from core.structured_logging import JsonFormatter, setup_logging


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_log_dir() -> str:
    """Return a unique /tmp directory for test log files."""
    return f"/tmp/test_logs_{uuid.uuid4().hex}"


def _close_handlers(logger: logging.Logger) -> None:
    """Close and remove all handlers from a logger."""
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


# ── JsonFormatter tests ───────────────────────────────────────────────────────

class TestJsonFormatter:

    def _record(self, msg: str = "hello", level: int = logging.INFO, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_output_is_valid_json(self):
        fmt = JsonFormatter()
        record = self._record("test message")
        line = fmt.format(record)
        data = json.loads(line)
        assert isinstance(data, dict)

    def test_standard_fields_present(self):
        fmt = JsonFormatter()
        record = self._record("hi there")
        data = json.loads(fmt.format(record))
        assert "timestamp" in data
        assert "level" in data
        assert "logger" in data
        assert "message" in data

    def test_message_content(self):
        fmt = JsonFormatter()
        record = self._record("my message")
        data = json.loads(fmt.format(record))
        assert data["message"] == "my message"
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"

    def test_timestamp_is_iso_utc(self):
        fmt = JsonFormatter()
        record = self._record("ts test")
        data = json.loads(fmt.format(record))
        ts = data["timestamp"]
        # Should be parseable ISO 8601 with UTC offset
        assert "T" in ts
        assert ts.endswith("+00:00")

    def test_extra_fields_included(self):
        fmt = JsonFormatter()
        record = self._record("extra test", agent="fred", session_id="abc123")
        data = json.loads(fmt.format(record))
        assert data["agent"] == "fred"
        assert data["session_id"] == "abc123"

    def test_standard_fields_not_duplicated_in_extra(self):
        fmt = JsonFormatter()
        record = self._record("dup test")
        data = json.loads(fmt.format(record))
        # These standard LogRecord internals must not appear at top level
        assert "levelno" not in data
        assert "pathname" not in data
        assert "lineno" not in data
        assert "funcName" not in data
        assert "msecs" not in data

    def test_exception_info_included(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("oops")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        data = json.loads(fmt.format(record))
        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "oops" in data["exception"]

    def test_percent_style_formatting(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s, value=%d",
            args=("world", 42),
            exc_info=None,
        )
        data = json.loads(fmt.format(record))
        assert data["message"] == "hello world, value=42"

    def test_output_is_single_line(self):
        fmt = JsonFormatter()
        record = self._record("single line test")
        line = fmt.format(record)
        assert "\n" not in line

    def test_non_serializable_value_uses_str(self):
        fmt = JsonFormatter()

        class Weird:
            def __str__(self):
                return "weird-repr"

        record = self._record("weird test", custom_obj=Weird())
        # Should not raise
        data = json.loads(fmt.format(record))
        assert data["custom_obj"] == "weird-repr"


# ── setup_logging tests ───────────────────────────────────────────────────────

class TestSetupLogging:

    def teardown_method(self):
        """Ensure root logger handlers are cleaned up after each test."""
        root = logging.getLogger()
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)

    def test_creates_log_file(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        assert (tmp_path / "logs" / "hub.log").exists()

    def test_file_handler_is_rotating(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].maxBytes == 10 * 1024 * 1024
        assert file_handlers[0].backupCount == 5

    def test_custom_max_bytes_and_backup_count(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir, max_bytes=1024, backup_count=3)
        root = logging.getLogger()
        fh = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert fh.maxBytes == 1024
        assert fh.backupCount == 3

    def test_stdout_handler_present(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        root = logging.getLogger()
        stream_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

    def test_stdout_plain_text_by_default(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir, json_stdout=False)
        root = logging.getLogger()
        stream_handler = next(
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        )
        assert not isinstance(stream_handler.formatter, JsonFormatter)

    def test_stdout_json_when_flag_set(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir, json_stdout=True)
        root = logging.getLogger()
        stream_handler = next(
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        )
        assert isinstance(stream_handler.formatter, JsonFormatter)

    def test_file_handler_always_json(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir, json_stdout=False)
        root = logging.getLogger()
        fh = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        assert isinstance(fh.formatter, JsonFormatter)

    def test_clears_existing_handlers(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        # Add a dummy handler first
        root = logging.getLogger()
        dummy = logging.StreamHandler()
        root.addHandler(dummy)
        pre_count = len(root.handlers)
        setup_logging(log_dir=log_dir)
        # Should have exactly 2 handlers (stdout + file), not pre_count + 2
        assert len(root.handlers) == 2
        dummy.close()

    def test_log_level_applied(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir, level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_slack_bolt_suppressed(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        assert logging.getLogger("slack_bolt").level == logging.WARNING

    def test_slack_sdk_suppressed(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        assert logging.getLogger("slack_sdk").level == logging.WARNING

    def test_file_log_contains_json(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        logger = logging.getLogger("test.file_content")
        logger.info("structured log test")
        # Flush and close file handlers
        root = logging.getLogger()
        for h in root.handlers:
            h.flush()
        log_file = tmp_path / "logs" / "hub.log"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        data = json.loads(lines[-1])
        assert data["message"] == "structured log test"
        assert data["level"] == "INFO"

    def test_calling_twice_does_not_duplicate_handlers(self, tmp_path):
        log_dir = str(tmp_path / "logs")
        os.makedirs(log_dir)
        setup_logging(log_dir=log_dir)
        setup_logging(log_dir=log_dir)
        root = logging.getLogger()
        assert len(root.handlers) == 2
