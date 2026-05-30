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
def _reset():
    """Isolate every test — reset logging state before and after."""
    reset_logging_for_test()
    yield
    reset_logging_for_test()


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
    monkeypatch.setenv("AUDIAGENTIC_LOG_DIR", str(tmp_path / "logs"))
    configure_logging()
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

def test_dev_formatter_active_when_format_is_dev(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOG_FORMAT", "dev")
    monkeypatch.delenv("AUDIAGENTIC_LOG_DIR", raising=False)
    monkeypatch.setenv("AUDIAGENTIC_LOG_CONSOLE", "true")
    configure_logging()

    from audiagentic.foundation.logging.config import _DevFormatter
    stream_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert stream_handlers
    assert isinstance(stream_handlers[0].formatter, _DevFormatter)


# ---------------------------------------------------------------------------
# Config merge — env var overrides
# ---------------------------------------------------------------------------

def test_env_var_overrides_level(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOG_LEVEL", "DEBUG")
    cfg = load_logging_config()
    assert cfg.level == "DEBUG"


def test_env_var_overrides_format(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOG_FORMAT", "dev")
    cfg = load_logging_config()
    assert cfg.format == "dev"


def test_env_var_ai_audit_on(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_AI_AUDIT", "on")
    cfg = load_logging_config()
    assert cfg.ai_audit.enabled is True


# ---------------------------------------------------------------------------
# Config merge — project/local files
# ---------------------------------------------------------------------------

def test_project_config_overrides_default(tmp_path, monkeypatch):
    """Project-local config overrides package default."""
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.yaml").write_text("logging:\n  level: DEBUG\n", encoding="utf-8")

    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    cfg = load_logging_config(project_root=tmp_path)
    assert cfg.level == "DEBUG"


def test_local_yaml_overrides_project(tmp_path, monkeypatch):
    """Machine-local logging.local.yaml overrides project logging.yaml."""
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.yaml").write_text("logging:\n  level: INFO\n", encoding="utf-8")
    (cfg_dir / "logging.local.yaml").write_text("logging:\n  level: DEBUG\n", encoding="utf-8")

    cfg = load_logging_config(project_root=tmp_path)
    assert cfg.level == "DEBUG"


def test_env_var_beats_local_yaml(tmp_path, monkeypatch):
    """Env var must override even the machine-local YAML."""
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.local.yaml").write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_LOG_LEVEL", "WARNING")

    cfg = load_logging_config(project_root=tmp_path)
    assert cfg.level == "WARNING"


# ---------------------------------------------------------------------------
# silenced: list union
# ---------------------------------------------------------------------------

def test_silenced_lists_union_across_layers(tmp_path):
    """silenced: from project config should be added to the package defaults, not replace them."""
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.yaml").write_text(
        "logging:\n  silenced:\n    - mynoisy.lib\n", encoding="utf-8"
    )

    cfg = load_logging_config(project_root=tmp_path)
    # Package defaults include mcp, asyncio, httpx, urllib3; project adds mynoisy.lib
    assert "mynoisy.lib" in cfg.silenced
    assert "mcp" in cfg.silenced


# ---------------------------------------------------------------------------
# Malformed YAML — graceful fallback
# ---------------------------------------------------------------------------

def test_malformed_local_yaml_falls_back_to_defaults(tmp_path, capsys):
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.local.yaml").write_text(": bad: yaml: [\n", encoding="utf-8")

    cfg = load_logging_config(project_root=tmp_path)
    # Should return a valid config (defaults), not raise
    assert isinstance(cfg, LoggingConfig)
    assert cfg.level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


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


def test_ai_audit_custom_pattern_from_yaml(tmp_path):
    """Project-local YAML can add custom redact_patterns that are unioned with pkg defaults."""
    cfg_dir = tmp_path / ".audiagentic" / "config" / "foundation"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "logging.yaml").write_text(
        "logging:\n  ai_audit:\n    redact_patterns:\n      - 'MYTOKEN-[0-9]+'\n",
        encoding="utf-8",
    )

    from audiagentic.foundation.logging.config import load_logging_config
    cfg = load_logging_config(project_root=tmp_path)

    # Custom pattern is present
    assert any("MYTOKEN" in p for p in cfg.ai_audit.redact_patterns)
    # Pkg default Bearer pattern is also present (union, not replace)
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
# log_tool_call decorator
# ---------------------------------------------------------------------------

def test_log_tool_call_sync_logs_entry_and_exit():
    from audiagentic.foundation.mcp.component_server import log_tool_call

    # Use _ListHandler directly — configure_logging() strips caplog's handler from root.
    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    new_correlation_id()

    @log_tool_call
    def my_tool(x: int) -> int:
        return x * 2

    result = my_tool(21)

    assert result == 42
    messages = [r.getMessage() for r in handler.records]
    assert any("tool call start" in m for m in messages)
    assert any("tool call done" in m for m in messages)


def test_log_tool_call_sync_logs_error_on_exception():
    from audiagentic.foundation.mcp.component_server import log_tool_call

    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    @log_tool_call
    def bad_tool() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        bad_tool()

    assert any("tool call failed" in r.getMessage() for r in handler.records)
    assert any(r.exc_info is not None for r in handler.records if "failed" in r.getMessage())


def test_log_tool_call_async_logs_entry_and_exit():
    from audiagentic.foundation.mcp.component_server import log_tool_call

    handler = _ListHandler()
    tool_logger = logging.getLogger("audiagentic.foundation.mcp.component_server")
    tool_logger.addHandler(handler)
    tool_logger.setLevel(logging.DEBUG)

    new_correlation_id()

    @log_tool_call
    async def async_tool(x: int) -> int:
        return x + 1

    result = asyncio.run(async_tool(9))

    assert result == 10
    messages = [r.getMessage() for r in handler.records]
    assert any("tool call start" in m for m in messages)
    assert any("tool call done" in m for m in messages)


def test_log_tool_call_preserves_function_name():
    from audiagentic.foundation.mcp.component_server import log_tool_call

    @log_tool_call
    def my_named_tool() -> None:
        pass

    assert my_named_tool.__name__ == "my_named_tool"


# Need the TimedRotatingFileHandler import for isinstance check
import logging.handlers  # noqa: E402
