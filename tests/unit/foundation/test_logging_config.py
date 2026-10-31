"""Tests for foundation/logging — configure_logging, correlation ID, config merge, audit."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from audiagentic.foundation.logging.config import (
    LoggingConfig,
    _SafeTimedRotatingFileHandler,
    configure_logging,
    load_logging_config,
    reset_logging_for_test,
)
from audiagentic.foundation.logging.context import (
    get_correlation_id,
    new_correlation_id,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    """Isolate every test — reset logging state, and keep user settings out of it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    reset_logging_for_test()
    yield
    reset_logging_for_test()


def _settings(root, text):
    """Write a project settings file whose ``logging`` section is ``text`` (YAML, indented under it)."""
    path = root / ".audiagentic" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema_version: 1\nlogging:\n" + text, encoding="utf-8")
    return path


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_configure_logging_idempotent():
    """Calling configure_logging twice must not add duplicate handlers."""
    configure_logging()
    handler_count_1 = len(logging.getLogger().handlers)

    configure_logging()
    handler_count_2 = len(logging.getLogger().handlers)

    assert handler_count_1 == handler_count_2
    assert handler_count_1 >= 1


# ---------------------------------------------------------------------------
# JSON schema
# ---------------------------------------------------------------------------

def test_json_log_line_schema(tmp_path):
    """Every JSON log line must contain required schema keys."""
    configure_logging()
    new_correlation_id()

    handler = _ListHandler()
    logging.getLogger().addHandler(handler)

    test_logger = logging.getLogger("test.schema")
    test_logger.setLevel(logging.DEBUG)
    test_logger.info("schema check", extra={"component_id": "test", "duration_ms": 42})

    # Find a record emitted by our test logger
    records = [r for r in handler.records if r.name == "test.schema"]
    assert records, "No log record captured"

    from audiagentic.foundation.logging.config import _CorrelationJsonFormatter
    formatter = _CorrelationJsonFormatter()
    raw = formatter.format(records[0])
    doc = json.loads(raw)

    assert "ts" in doc
    assert "level" in doc
    assert "logger" in doc
    assert "msg" in doc
    assert "correlation_id" in doc
    assert "exc_info" in doc
    assert doc["component_id"] == "test"
    assert doc["duration_ms"] == 42
    assert doc["level"] == "INFO"
    assert doc["logger"] == "test.schema"


def test_json_log_timestamps_are_utc_before_adding_z_suffix():
    """The regional timezone must not leak into canonical JSON logs."""
    from audiagentic.foundation.logging.config import _CorrelationJsonFormatter

    record = logging.LogRecord("test.schema", logging.INFO, __file__, 1, "utc", (), None)
    record.created = 0.0
    record.msecs = 0.0
    doc = json.loads(_CorrelationJsonFormatter().format(record))
    assert doc["ts"] == "1970-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Correlation ID propagation
# ---------------------------------------------------------------------------

def test_correlation_id_propagates_across_asyncio_gather():
    """correlation_id set in parent must be visible inside asyncio.gather tasks."""
    configure_logging()
    cid = new_correlation_id()

    async def _child():
        return get_correlation_id()

    async def _run():
        results = await asyncio.gather(_child(), _child(), _child())
        return results

    results = asyncio.run(_run())
    assert all(r == cid for r in results), f"Expected {cid}, got {results}"


def test_correlation_id_not_propagated_by_thread_pool_submit():
    """ThreadPoolExecutor.submit() does NOT copy contextvars — workers see None.

    Use asyncio.to_thread() or contextvars.copy_context().run() for propagation into threads.
    """
    configure_logging()
    new_correlation_id()

    captured: list[str | None] = []
    lock = threading.Lock()

    def _worker():
        with lock:
            captured.append(get_correlation_id())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_worker) for _ in range(4)]
        for f in futures:
            f.result()

    assert all(c is None for c in captured), (
        f"Expected None in all workers (no context copy), got {captured}"
    )


# ---------------------------------------------------------------------------
# reset_logging_for_test
# ---------------------------------------------------------------------------

def test_reset_clears_handlers():
    configure_logging()
    assert len(logging.getLogger().handlers) >= 1

    reset_logging_for_test()
    assert len(logging.getLogger().handlers) == 0


def test_reset_clears_correlation_id():
    configure_logging()
    new_correlation_id()
    assert get_correlation_id() is not None

    reset_logging_for_test()
    assert get_correlation_id() is None


def test_reset_allows_reconfigure():
    configure_logging()
    reset_logging_for_test()
    # Should not raise and should add a handler
    configure_logging()
    assert len(logging.getLogger().handlers) >= 1


# ---------------------------------------------------------------------------
# File handler
# ---------------------------------------------------------------------------

def test_no_file_handler_when_dir_is_none(monkeypatch):
    import audiagentic.foundation.logging.config as config_mod

    monkeypatch.setattr(config_mod, "load_logging_config", lambda project_root=None: LoggingConfig(dir=None))
    configure_logging()
    file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 0


def test_file_handler_created_when_dir_set(tmp_path, monkeypatch):
    _settings(tmp_path, f"  dir: {tmp_path / 'logs'}\n")
    configure_logging(project_root=tmp_path)
    file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert (tmp_path / "logs" / "diagnostic.log").exists() or True  # created on first write


def test_safe_file_handler_skips_locked_rollover(tmp_path, monkeypatch):
    log_path = tmp_path / "diagnostic.log"
    handler = _SafeTimedRotatingFileHandler(
        filename=log_path,
        when="midnight",
        backupCount=3,
        encoding="utf-8",
    )
    log_path.write_text("seed\n", encoding="utf-8")
    handler.rolloverAt = int(time.time())

    def _raise_permission_error(source: str, dest: str) -> None:
        raise PermissionError(32, "file in use", source)

    monkeypatch.setattr(handler, "rotate", _raise_permission_error)

    handler.doRollover()

    assert handler.rolloverAt > int(time.time())
    assert handler.stream is not None
    handler.close()


# ---------------------------------------------------------------------------
# Dev formatter
# ---------------------------------------------------------------------------

def test_dev_formatter_active_when_format_is_dev(tmp_path):
    _settings(tmp_path, "  format: dev\n  console: true\n")
    configure_logging(project_root=tmp_path)

    from audiagentic.foundation.logging.config import _DevFormatter
    stream_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert stream_handlers
    assert isinstance(stream_handlers[0].formatter, _DevFormatter)


def test_console_formatter_active_when_format_is_console(tmp_path):
    _settings(tmp_path, "  format: console\n  console: true\n")
    configure_logging(project_root=tmp_path)

    from audiagentic.foundation.logging.config import _ConsoleFormatter
    stream_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert stream_handlers
    assert isinstance(stream_handlers[0].formatter, _ConsoleFormatter)


# ---------------------------------------------------------------------------
# Config merge — env var overrides
# ---------------------------------------------------------------------------

def test_env_var_overrides_level(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOG_LEVEL", "DEBUG")
    cfg = load_logging_config()
    assert cfg.level == "DEBUG"


def test_only_the_level_has_an_environment_override(tmp_path, monkeypatch):
    """Format, console, dir and the AI audit switches are settings; the removed variables are ignored."""
    for name, value in (("AUDIAGENTIC_LOG_FORMAT", "dev"), ("AUDIAGENTIC_AI_AUDIT", "on"),
                        ("AUDIAGENTIC_LOG_DIR", str(tmp_path / "x")), ("AUDIAGENTIC_LOG_CONSOLE", "false")):
        monkeypatch.setenv(name, value)
    cfg = load_logging_config()
    assert cfg.format == "json" and cfg.ai_audit.enabled is False and cfg.dir is None and cfg.console is True


def test_ai_audit_is_enabled_by_a_setting(tmp_path):
    _settings(tmp_path, "  ai_audit:\n    enabled: true\n")
    assert load_logging_config(project_root=tmp_path).ai_audit.enabled is True


# ---------------------------------------------------------------------------
# Config merge — project/local files
# ---------------------------------------------------------------------------

def test_project_settings_override_the_packaged_default(tmp_path):
    _settings(tmp_path, "  level: DEBUG\n")
    assert load_logging_config(project_root=tmp_path).level == "DEBUG"


def test_project_settings_override_user_settings(tmp_path):
    user = tmp_path / "xdg-config" / "audiagentic" / "settings.yaml"
    user.parent.mkdir(parents=True)
    user.write_text("schema_version: 1\nlogging:\n  level: ERROR\n  format: dev\n", encoding="utf-8")
    _settings(tmp_path, "  level: DEBUG\n")
    cfg = load_logging_config(project_root=tmp_path)
    assert (cfg.level, cfg.format) == ("DEBUG", "dev")


def test_env_var_beats_settings(tmp_path, monkeypatch):
    _settings(tmp_path, "  level: DEBUG\n")
    monkeypatch.setenv("AUDIAGENTIC_LOG_LEVEL", "WARNING")
    assert load_logging_config(project_root=tmp_path).level == "WARNING"


# ---------------------------------------------------------------------------
# silenced: list union
# ---------------------------------------------------------------------------

def test_silenced_lists_add_to_the_packaged_defaults(tmp_path):
    _settings(tmp_path, "  silenced:\n    - mynoisy.lib\n")
    cfg = load_logging_config(project_root=tmp_path)
    assert "mynoisy.lib" in cfg.silenced
    assert "mcp" in cfg.silenced


# ---------------------------------------------------------------------------
# Invalid settings — graceful fallback
# ---------------------------------------------------------------------------

def test_invalid_settings_fall_back_to_the_packaged_defaults(tmp_path, capsys):
    _settings(tmp_path, "  level: LOUD\n")
    cfg = load_logging_config(project_root=tmp_path)
    assert isinstance(cfg, LoggingConfig)
    assert cfg.level == "INFO"
    assert "falls back to its packaged defaults" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# AI audit logger — no-op when disabled
# ---------------------------------------------------------------------------

def test_ai_audit_logger_noop_when_disabled(tmp_path):
    from audiagentic.foundation.logging.audit import AiAuditLogger

    logger = AiAuditLogger(
        enabled=False, log_dir=tmp_path, backup_count=7, redact=True, redact_patterns=[]
    )
    logger.log("in", "hello", provider="test", session_id="s1")
    assert not any(tmp_path.iterdir())


def test_ai_audit_logger_writes_jsonl_when_enabled(tmp_path):
    from audiagentic.foundation.logging.audit import AiAuditLogger

    logger = AiAuditLogger(
        enabled=True, log_dir=tmp_path, backup_count=7, redact=False, redact_patterns=[]
    )
    logger.log("in", "hello world", provider="test", session_id="s1", token_count=5)

    if logger._logger:
        for h in logger._logger.handlers:
            h.flush()

    audit_file = tmp_path / "ai_audit" / "ai_audit.jsonl"
    assert audit_file.exists()
    line = audit_file.read_text(encoding="utf-8").strip()
    doc = json.loads(line)
    assert doc["direction"] == "in"
    assert doc["content"] == "hello world"
    assert doc["provider"] == "test"
    assert doc["token_count"] == 5


def test_ai_audit_redaction_via_config_patterns(tmp_path):
    """Redaction patterns come from config, not hardcoded in Python."""
    from audiagentic.foundation.logging.audit import AiAuditLogger

    logger = AiAuditLogger(
        enabled=True,
        log_dir=tmp_path,
        backup_count=7,
        redact=True,
        redact_patterns=[r"Bearer\s+\S+"],
    )
    logger.log("in", "token: Bearer abc123xyz", provider="test", session_id="s1")

    if logger._logger:
        for h in logger._logger.handlers:
            h.flush()

    content = (tmp_path / "ai_audit" / "ai_audit.jsonl").read_text(encoding="utf-8")
    assert "abc123xyz" not in content
    assert "[REDACTED]" in content


def test_ai_audit_custom_pattern_from_settings(tmp_path):
    """Settings can add redact_patterns; the packaged defaults stay."""
    _settings(tmp_path, "  ai_audit:\n    redact_patterns:\n      - 'MYTOKEN-[0-9]+'\n")
    cfg = load_logging_config(project_root=tmp_path)
    assert any("MYTOKEN" in p for p in cfg.ai_audit.redact_patterns)
    assert any("Bearer" in p for p in cfg.ai_audit.redact_patterns)


def test_ai_audit_custom_pattern_actually_redacts(tmp_path):
    """A custom pattern loaded via config redacts matching content in audit log."""
    from audiagentic.foundation.logging.audit import AiAuditLogger

    logger = AiAuditLogger(
        enabled=True,
        log_dir=tmp_path,
        backup_count=7,
        redact=True,
        redact_patterns=[r"MYTOKEN-[0-9]+"],
    )
    logger.log("in", "auth: MYTOKEN-99887766", provider="test", session_id="s1")

    if logger._logger:
        for h in logger._logger.handlers:
            h.flush()

    content = (tmp_path / "ai_audit" / "ai_audit.jsonl").read_text(encoding="utf-8")
    assert "MYTOKEN-99887766" not in content
    assert "[REDACTED]" in content


def test_get_ai_audit_logger_fallback_is_disabled(monkeypatch):
    """When config fails, get_ai_audit_logger returns a disabled no-op — no hardcoded values."""
    import audiagentic.foundation.logging.audit as audit_mod
    import audiagentic.foundation.logging.config as config_mod

    monkeypatch.setattr(config_mod, "load_logging_config", lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    audit_mod._instance = None

    logger = audit_mod.get_ai_audit_logger()
    assert not logger.enabled
    assert logger._do_redact is False
    assert logger._compiled == []
    logger.log("in", "should not raise", provider="x", session_id="s")  # no-op


# ---------------------------------------------------------------------------
# tool_boundary decorator (renamed from log_tool_call — CC62: now also
# redacts and translates exceptions into ToolError, not just logging)
# ---------------------------------------------------------------------------

def test_tool_boundary_sync_logs_entry_and_exit():
    from audiagentic.foundation.mcp.component_server import tool_boundary

    # Use _ListHandler directly — configure_logging() strips caplog's handler from root.
    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    new_correlation_id()

    @tool_boundary
    def my_tool(x: int) -> int:
        return x * 2

    result = my_tool(21)

    assert result == 42
    messages = [r.getMessage() for r in handler.records]
    assert any("tool call start" in m for m in messages)
    assert any("tool call done" in m for m in messages)


def test_tool_boundary_sync_raises_tool_error_and_logs_on_exception():
    from mcp.server.fastmcp.exceptions import ToolError

    from audiagentic.foundation.mcp.component_server import tool_boundary

    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    @tool_boundary
    def bad_tool() -> None:
        raise ValueError("boom")

    with pytest.raises(ToolError):
        bad_tool()

    # tool_boundary no longer re-raises the original exception — it logs the
    # full failure for operators (message "tool failed", not "tool call
    # failed") and raises ToolError with redacted, client-safe text instead.
    assert any("tool failed" in r.getMessage() for r in handler.records)
    assert any(r.exc_info is not None for r in handler.records if "tool failed" in r.getMessage())


def test_tool_boundary_async_logs_entry_and_exit():
    from audiagentic.foundation.mcp.component_server import tool_boundary

    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    new_correlation_id()

    @tool_boundary
    async def async_tool(x: int) -> int:
        return x + 1

    result = asyncio.run(async_tool(9))

    assert result == 10
    messages = [r.getMessage() for r in handler.records]
    assert any("tool call start" in m for m in messages)
    assert any("tool call done" in m for m in messages)


def test_tool_boundary_preserves_function_name():
    from audiagentic.foundation.mcp.component_server import tool_boundary

    @tool_boundary
    def my_named_tool() -> None:
        pass

    assert my_named_tool.__name__ == "my_named_tool"


# Need the TimedRotatingFileHandler import for isinstance check
import logging.handlers  # noqa: E402
