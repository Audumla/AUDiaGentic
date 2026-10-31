"""Central logging configuration for AUDiaGentic.

Provides configure_logging() — the single entry point for stdlib logging setup.
The ``logging`` section of the resolved settings (packaged defaults in the vendor settings, then
the user and project settings) is the configuration; ``audiagentic config show logging --origin``
explains each value. ``AUDIAGENTIC_LOG_LEVEL`` is the one documented diagnostic override and always
wins. Two lists are additive, so a scope can add entries but never drop a packaged one (a redaction
default must not vanish by accident): ``silenced`` and ``ai_audit.redact_patterns``.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.cli_io import print_error
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.logging.context import reset_correlation_id
from audiagentic.foundation.logging.formatters import (
    _ConsoleFormatter,
    _CorrelationJsonFormatter,
    _DevFormatter,
    _SafeTimedRotatingFileHandler,
)

_logger = logging.getLogger(__name__)
_configured = False
_loaded_config: LoggingConfig | None = None

# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class DiagnosticConfig:
    backup_count: int = 30


@dataclass
class AiAuditConfig:
    enabled: bool = False
    level: str = "full"
    redact: bool = True
    backup_count: int = 7
    redact_patterns: list[str] = field(default_factory=list)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"
    console: bool = True   # False = suppress stderr handler; logs go to file only
    dir: Path | None = None
    diagnostic: DiagnosticConfig = field(default_factory=DiagnosticConfig)
    ai_audit: AiAuditConfig = field(default_factory=AiAuditConfig)
    loggers: dict[str, str] = field(default_factory=dict)
    silenced: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _packaged_logging() -> dict[str, Any]:
    """The packaged ``logging`` defaults, read straight from the vendor settings file."""
    from audiagentic.foundation.config.settings import vendor_settings_path
    from audiagentic.foundation.io import load_yaml_file

    section = load_yaml_file(vendor_settings_path()).get("logging")
    return section if isinstance(section, dict) else {}


def _settings_logging(project_root: Path | None) -> dict[str, Any]:
    """The effective ``logging`` section; the packaged defaults when settings cannot be read."""
    try:
        from audiagentic.foundation.config.settings import resolve_settings_cached

        resolved = (
            resolve_settings_cached(project_root) if project_root is not None
            else resolve_settings_cached(machine_only=True)
        )
        section = resolved.get("logging")
        return dict(section) if isinstance(section, dict) else {}
    except AudiaGenticError:
        print_error(
            "[audiagentic] WARNING: settings are invalid, so logging falls back to its packaged defaults"
        )
        return _packaged_logging()


def _union(*lists: Any) -> list[str]:
    return list(dict.fromkeys(str(item) for items in lists for item in (items or [])))


def _apply_env_override(log: dict[str, Any]) -> dict[str, Any]:
    """``AUDIAGENTIC_LOG_LEVEL``: the documented diagnostic override; everything else is a setting."""
    if val := os.environ.get("AUDIAGENTIC_LOG_LEVEL"):
        log["level"] = val
    return log


def _dict_to_config(log: dict[str, Any]) -> LoggingConfig:
    dir_val = log.get("dir")
    diag = log.get("diagnostic") or {}
    audit = log.get("ai_audit") or {}
    return LoggingConfig(
        level=str(log.get("level", "INFO")).upper(),
        format=str(log.get("format", "json")).lower(),
        console=bool(log.get("console", True)),
        dir=Path(dir_val) if dir_val else None,
        diagnostic=DiagnosticConfig(
            backup_count=int(diag.get("backup_count", 30)),
        ),
        ai_audit=AiAuditConfig(
            enabled=bool(audit.get("enabled", False)),
            level=str(audit.get("level", "full")),
            redact=bool(audit.get("redact", True)),
            backup_count=int(audit.get("backup_count", 7)),
            redact_patterns=list(audit.get("redact_patterns") or []),
        ),
        loggers={str(k): str(v) for k, v in (log.get("loggers") or {}).items()},
        silenced=list(log.get("silenced") or []),
    )


def _find_project_root_from_env_or_cwd() -> Path | None:
    """Walk up from CWD looking for .audiagentic/. Max 10 levels, 500ms cap."""
    from audiagentic.foundation.paths.project import find_project_root

    return find_project_root()


_discovered_root: Path | None | bool = False  # False = not yet searched


def _resolve_project_root(project_root: Path | None) -> Path | None:
    global _discovered_root
    if project_root is not None:
        return project_root
    if _discovered_root is False:
        _discovered_root = _find_project_root_from_env_or_cwd()
    return _discovered_root  # type: ignore[return-value]


def load_logging_config(project_root: Path | None = None) -> LoggingConfig:
    """Load and merge logging config across all tiers."""
    global _loaded_config
    if _loaded_config is not None:
        return _loaded_config

    resolved_root = _resolve_project_root(project_root)
    log = _apply_env_override(_settings_logging(resolved_root))
    packaged = _packaged_logging()
    log["silenced"] = _union(packaged.get("silenced"), log.get("silenced"))
    audit = dict(log.get("ai_audit") or {})
    audit["redact_patterns"] = _union(
        (packaged.get("ai_audit") or {}).get("redact_patterns"), audit.get("redact_patterns"),
    )
    log["ai_audit"] = audit
    cfg = _dict_to_config(log)
    _loaded_config = cfg

    _logger.debug(
        "logging config loaded: level=%s format=%s dir=%s",
        cfg.level,
        cfg.format,
        cfg.dir,
    )
    return cfg


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------

def configure_logging(project_root: Path | None = None) -> None:
    """Configure stdlib logging. Idempotent — safe to call multiple times."""
    global _configured
    if _configured:
        return
    _configured = True

    cfg = load_logging_config(project_root)

    root = logging.getLogger()
    root.setLevel(cfg.level)

    # Remove any handlers added before configure_logging was called
    for h in list(root.handlers):
        root.removeHandler(h)

    # Formatter
    _FORMATTER_REGISTRY: dict[str, Any] = {
        "dev": lambda colour: _DevFormatter(colour=colour),
        "console": lambda colour: _ConsoleFormatter(colour=colour),
        "json": lambda _: _CorrelationJsonFormatter(),
    }

    use_colour = sys.stderr.isatty() and cfg.format == "dev"
    formatter_factory = _FORMATTER_REGISTRY.get(cfg.format, _FORMATTER_REGISTRY["json"])
    formatter = formatter_factory(use_colour)

    # Stream handler (suppressed when console: false and a file dir is set)
    if cfg.console or cfg.dir is None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    # File handler (when dir is set)
    if cfg.dir is not None:
        try:
            cfg.dir.mkdir(parents=True, exist_ok=True)
            log_file = cfg.dir / "diagnostic.log"
            file_handler = _SafeTimedRotatingFileHandler(
                filename=log_file,
                when="midnight",
                backupCount=cfg.diagnostic.backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(_CorrelationJsonFormatter())
            root.addHandler(file_handler)
        except OSError:
            _logger.warning("Could not create log file handler at %s", cfg.dir, exc_info=True)

    # Per-logger overrides
    for logger_name, level in cfg.loggers.items():
        logging.getLogger(logger_name).setLevel(level.upper())

    # Silence noisy third-party loggers
    for logger_name in cfg.silenced:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def reset_logging_for_test() -> None:
    """Reset all logging state. Call in test teardown to prevent cross-test leakage."""
    global _configured, _loaded_config, _discovered_root
    _configured = False
    _loaded_config = None
    _discovered_root = False

    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            h.close()
        except Exception:
            pass
        root.removeHandler(h)
    root.setLevel(logging.WARNING)

    reset_correlation_id()

    # Reset audit logger singleton so it is rebuilt from fresh config on next access
    try:
        from audiagentic.foundation.logging.audit import reset_ai_audit_logger
        reset_ai_audit_logger()
    except Exception:
        pass
