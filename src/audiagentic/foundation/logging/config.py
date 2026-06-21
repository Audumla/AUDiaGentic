"""Central logging configuration for AUDiaGentic.

Provides configure_logging() — the single entry point for stdlib logging setup.
Uses the layered config system (runtime/config/layered.py) with namespace
'foundation/logging', then applies a fourth machine-local tier and env var
overrides on top.

Tier precedence (lowest → highest):
  1. src/audiagentic/config/provisioning/foundation/logging.yaml  (package default)
  2. ~/.audiagentic/config/foundation/logging.yaml                (user-global)
  3. <project>/.audiagentic/config/foundation/logging.yaml        (project, committed)
  4. <project>/.audiagentic/config/foundation/logging.local.yaml  (machine-local, gitignored)
  5. Env vars                                                      (always wins)
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.cli_io import print_error
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
# Path resolution
# ---------------------------------------------------------------------------

def _find_pkg_root() -> Path:
    from audiagentic.foundation.paths.package import find_package_root
    return find_package_root(Path(__file__))

_PKG_DEFAULT: Path | None = None

def _pkg_default() -> Path:
    global _PKG_DEFAULT
    if _PKG_DEFAULT is None:
        _PKG_DEFAULT = _find_pkg_root() / "config" / "provisioning" / "foundation" / "logging.yaml"
    return _PKG_DEFAULT


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

def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay onto base. Lists are replaced (caller handles silenced union)."""
    from copy import deepcopy
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _safe_load_layered(project_root: Path | None) -> dict[str, Any]:
    """Call load_layered_config, catching malformed YAML/config errors."""
    try:
        from audiagentic.foundation.config import load_layered_config
        return load_layered_config(
            pkg_default_path=_pkg_default(),
            project_root=project_root,
            namespace="foundation/logging",
        )
    except AudiaGenticError:
        print_error(
            "[audiagentic] WARNING: logging config malformed in one of the config tiers,"
            " falling back to package defaults"
        )
        try:
            from audiagentic.foundation.io import load_yaml_file
            return load_yaml_file(_pkg_default())
        except Exception:
            return {}


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply env var overrides to the raw merged dict (mutates in place, returns it)."""
    log = raw.setdefault("logging", {})

    if val := os.environ.get("AUDIAGENTIC_LOG_LEVEL"):
        log["level"] = val
    if val := os.environ.get("AUDIAGENTIC_LOG_FORMAT"):
        log["format"] = val
    if val := os.environ.get("AUDIAGENTIC_LOG_CONSOLE"):
        log["console"] = val.lower() not in ("0", "false", "off", "no")
    if val := os.environ.get("AUDIAGENTIC_LOG_DIR"):
        log["dir"] = val

    diag = log.setdefault("diagnostic", {})
    if val := os.environ.get("AUDIAGENTIC_LOG_BACKUP_COUNT"):
        try:
            diag["backup_count"] = int(val)
        except ValueError:
            pass

    audit = log.setdefault("ai_audit", {})
    if val := os.environ.get("AUDIAGENTIC_AI_AUDIT"):
        audit["enabled"] = val.lower() in ("1", "true", "on", "yes")
    if val := os.environ.get("AUDIAGENTIC_AI_AUDIT_LEVEL"):
        audit["level"] = val
    if val := os.environ.get("AUDIAGENTIC_AI_AUDIT_REDACT"):
        audit["redact"] = val.lower() not in ("0", "false", "off", "no")

    return raw


def _dict_to_config(
    raw: dict[str, Any],
    silenced_union: list[str],
    redact_patterns_union: list[str],
) -> LoggingConfig:
    log = raw.get("logging", {})
    dir_val = log.get("dir")
    diag = log.get("diagnostic", {})
    audit = log.get("ai_audit", {})
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
            redact_patterns=redact_patterns_union,
        ),
        loggers={str(k): str(v) for k, v in log.get("loggers", {}).items()},
        silenced=silenced_union,
    )


def _find_project_root_from_env_or_cwd() -> Path | None:
    """Walk up from CWD looking for .audiagentic/. Max 10 levels, 500ms cap."""
    from audiagentic.paths import find_project_root

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

    # Load pkg default lists separately — load_layered_config replaces lists entirely,
    # so we capture the base values before they are overwritten by project config.
    try:
        from audiagentic.foundation.io import load_yaml_file as _lyf
        _pkg_raw = _lyf(_pkg_default()).get("logging", {})
        _pkg_silenced: list[str] = list(_pkg_raw.get("silenced", []))
        _pkg_redact_patterns: list[str] = list(
            _pkg_raw.get("ai_audit", {}).get("redact_patterns", [])
        )
    except Exception:
        _pkg_silenced = []
        _pkg_redact_patterns = []

    # Tiers 1-3 via load_layered_config
    raw = _safe_load_layered(resolved_root)

    # Both silenced and redact_patterns are additive — start with pkg defaults.
    silenced_sets: list[list[str]] = [
        _pkg_silenced,
        list(raw.get("logging", {}).get("silenced", [])),
    ]
    redact_patterns_sets: list[list[str]] = [
        _pkg_redact_patterns,
        list(raw.get("logging", {}).get("ai_audit", {}).get("redact_patterns", [])),
    ]

    # Tier 4: machine-local override
    if resolved_root is not None:
        local_path = resolved_root / ".audiagentic" / "config" / "foundation" / "logging.local.yaml"
        if local_path.exists():
            try:
                from audiagentic.foundation.io import load_yaml_file
                local = load_yaml_file(local_path)
                silenced_sets.append(list(local.get("logging", {}).get("silenced", [])))
                redact_patterns_sets.append(
                    list(local.get("logging", {}).get("ai_audit", {}).get("redact_patterns", []))
                )
                raw = _deep_merge(raw, local)
            except AudiaGenticError:
                print_error(
                    f"[audiagentic] WARNING: {local_path} is malformed, skipping"
                )

    # Tier 5: env vars
    raw = _apply_env_overrides(raw)

    def _union(sets: list[list[str]]) -> list[str]:
        return list(dict.fromkeys(s for tier in sets for s in tier))

    silenced_union = _union(silenced_sets)
    redact_patterns_union = _union(redact_patterns_sets)

    cfg = _dict_to_config(raw, silenced_union, redact_patterns_union)
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
    use_colour = sys.stderr.isatty() and cfg.format == "dev"
    formatter: logging.Formatter
    if cfg.format == "dev":
        formatter = _DevFormatter(colour=use_colour)
    elif cfg.format == "console":
        formatter = _ConsoleFormatter(colour=use_colour)
    else:
        formatter = _CorrelationJsonFormatter()

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
