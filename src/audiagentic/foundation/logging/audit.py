"""AI communication audit logger.

Captures incoming prompts, model reasoning, and outgoing responses as JSONL
when AUDIAGENTIC_AI_AUDIT=on (or ai_audit.enabled: true in logging config).
Off by default — log() is a no-op with zero overhead when disabled.

Usage:
    from audiagentic.foundation.logging.audit import get_ai_audit_logger

    audit = get_ai_audit_logger()
    audit.log("in", user_message, provider="claude", session_id=sid)
    audit.log("think", reasoning, provider="claude", session_id=sid, token_count=512)
    audit.log("out", response, provider="claude", session_id=sid)
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
from datetime import datetime, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class _RedactionFilter(logging.Filter):
    def __init__(self, patterns: list[re.Pattern]) -> None:  # type: ignore[type-arg]
        super().__init__()
        self._patterns = patterns

    def _apply_redaction(self, text: str) -> str:
        for p in self._patterns:
            text = p.sub("[REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._apply_redaction(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._apply_redaction(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: self._apply_redaction(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


# ---------------------------------------------------------------------------
# JSONL formatter
# ---------------------------------------------------------------------------

class _AuditJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


# ---------------------------------------------------------------------------
# AiAuditLogger
# ---------------------------------------------------------------------------

class AiAuditLogger:
    """Audit logger for AI communication turns.

    No-op when disabled — log() returns immediately with no I/O.
    """

    def __init__(
        self,
        enabled: bool,
        log_dir: Path | None,
        backup_count: int,
        redact: bool,
        redact_patterns: list[str],
    ) -> None:
        self._enabled = enabled
        self._do_redact = redact
        self._compiled: list[re.Pattern] = (  # type: ignore[type-arg]
            [re.compile(p, re.IGNORECASE) for p in redact_patterns]
            if redact and redact_patterns
            else []
        )
        self._logger: logging.Logger | None = None

        if enabled and log_dir is not None:
            self._setup_handler(log_dir, backup_count)

    def _apply_redaction(self, text: str) -> str:
        for p in self._compiled:
            text = p.sub("[REDACTED]", text)
        return text

    def _setup_handler(self, log_dir: Path, backup_count: int) -> None:
        audit_dir = log_dir / "ai_audit"
        try:
            audit_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            _logger.warning("Could not create ai_audit log dir %s", audit_dir, exc_info=True)
            return

        logger = logging.getLogger("ai_audit")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # never mix with diagnostic log

        handler = logging.handlers.TimedRotatingFileHandler(
            filename=audit_dir / "ai_audit.jsonl",
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(_AuditJsonFormatter())
        if self._do_redact and self._compiled:
            handler.addFilter(_RedactionFilter(self._compiled))
        logger.addHandler(handler)
        self._logger = logger

    def log(
        self,
        direction: str,
        content: str,
        *,
        provider: str,
        session_id: str,
        token_count: int | None = None,
    ) -> None:
        if not self._enabled or self._logger is None:
            return

        doc = {
            "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "provider": provider,
            "session_id": session_id,
            "direction": direction,
            "token_count": token_count,
            "content": self._apply_redaction(content) if self._do_redact else content,
        }
        self._logger.info(json.dumps(doc, default=str))

    @property
    def enabled(self) -> bool:
        return self._enabled


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: AiAuditLogger | None = None


def get_ai_audit_logger() -> AiAuditLogger:
    """Return the process-global AiAuditLogger.

    Initialised from the active logging config on first call. The instance is
    a no-op until configure_logging() has been called.
    """
    global _instance
    if _instance is None:
        try:
            from audiagentic.foundation.logging.config import load_logging_config
            cfg = load_logging_config()
            _instance = AiAuditLogger(
                enabled=cfg.ai_audit.enabled,
                log_dir=cfg.dir,
                backup_count=cfg.ai_audit.backup_count,
                redact=cfg.ai_audit.redact,
                redact_patterns=cfg.ai_audit.redact_patterns,
            )
        except Exception:
            _instance = AiAuditLogger(
                enabled=False, log_dir=None, backup_count=0, redact=False, redact_patterns=[]
            )
    return _instance


def reset_ai_audit_logger() -> None:
    """Reset singleton — used by reset_logging_for_test()."""
    global _instance
    if _instance is not None and _instance._logger is not None:
        for h in list(_instance._logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            _instance._logger.removeHandler(h)
    _instance = None
