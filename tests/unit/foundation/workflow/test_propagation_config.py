"""Unit tests for foundation/workflow/propagation/propagation_config.py."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.propagation.propagation_config import (
    _import_callable,
    bind_callables,
    load_config,
    validate,
)

# ── load_config ───────────────────────────────────────────────────────────────

def test_load_config_missing_path_returns_disabled() -> None:
    cfg = load_config(None)
    assert cfg["global"]["enabled"] is False


def test_load_config_nonexistent_file_returns_disabled(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["global"]["enabled"] is False


def test_load_config_empty_yaml_returns_empty_dict(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("", encoding="utf-8")
    cfg = load_config(path)
    assert isinstance(cfg, dict)


def test_load_config_valid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("global:\n  enabled: true\n  max_depth: 5\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["global"]["enabled"] is True
    assert cfg["global"]["max_depth"] == 5


def test_load_config_malformed_yaml_returns_disabled(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text(":\n  - bad: [unclosed", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["global"]["enabled"] is False


def test_load_config_reads_utf8_content(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text('global:\n  note: "héllo wörld"\n', encoding="utf-8")
    cfg = load_config(path)
    assert cfg["global"]["note"] == "héllo wörld"


# ── bind_callables ────────────────────────────────────────────────────────────

def test_bind_callables_resolves_dotted_path() -> None:
    config = {
        "rules": {
            "none": {
                "logic": "audiagentic.foundation.workflow.propagation.rules.rule_none",
                "enabled": True,
            }
        }
    }
    bind_callables(config)
    assert callable(config["rules"]["none"]["logic"])


def test_bind_callables_already_callable_unchanged() -> None:
    def sentinel(*_args) -> bool:
        return False

    config = {"rules": {"x": {"logic": sentinel}}}
    bind_callables(config)
    assert config["rules"]["x"]["logic"] is sentinel


def test_bind_callables_invalid_path_raises() -> None:
    config = {"rules": {"bad": {"logic": "audiagentic.does.not.exist.fn"}}}
    with pytest.raises(AudiaGenticError, match="Failed to load rules bad"):
        bind_callables(config)


def test_bind_callables_invalid_action_raises() -> None:
    config = {"actions": {"bad": {"logic": "audiagentic.does.not.exist.fn"}}}
    with pytest.raises(AudiaGenticError, match="Failed to load actions bad"):
        bind_callables(config)


def test_bind_callables_no_logic_key_unchanged() -> None:
    config = {"rules": {"x": {"enabled": True}}}
    bind_callables(config)
    assert "logic" not in config["rules"]["x"]


# ── _import_callable ──────────────────────────────────────────────────────────

def test_import_callable_returns_function() -> None:
    fn = _import_callable("audiagentic.foundation.workflow.propagation.rules.rule_none")
    assert callable(fn)


def test_import_callable_invalid_ref_raises_value_error() -> None:
    with pytest.raises(AudiaGenticError, match="Invalid callable reference"):
        _import_callable("no_dot")


def test_import_callable_nonexistent_module_raises_import_error() -> None:
    with pytest.raises(ImportError):
        _import_callable("audiagentic.does.not.exist.fn")


def test_import_callable_nonexistent_attr_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        _import_callable("audiagentic.foundation.workflow.propagation.rules.no_such_fn")


# ── validate ─────────────────────────────────────────────────────────────────

def test_validate_empty_config_no_errors() -> None:
    assert validate({}, None) == []


def test_validate_required_field_missing_reports_error() -> None:
    config = {
        "validation": {"required_fields": ["global.enabled"]},
        "global": {},
    }
    errors = validate(config, None)
    assert any("global.enabled" in e for e in errors)


def test_validate_required_field_present_no_error() -> None:
    config = {
        "validation": {"required_fields": ["global.enabled"]},
        "global": {"enabled": True},
    }
    assert validate(config, None) == []


def test_validate_required_rule_missing_reports_error() -> None:
    config = {
        "validation": {"required_rules": ["all_children_in_set"]},
        "rules": {},
    }
    errors = validate(config, None)
    assert any("all_children_in_set" in e for e in errors)


def test_validate_unknown_state_in_kind_reports_error() -> None:
    config = {
        "kinds": {
            "task": {
                "state_rules": {
                    "nonexistent_state": {"rule": "none", "new_state": "done"},
                }
            }
        }
    }
    errors = validate(config, lambda kind: ["draft", "active", "done"])
    assert any("nonexistent_state" in e for e in errors)


def test_validate_rejects_state_valid_only_for_other_kind() -> None:
    config = {
        "kinds": {
            "request": {
                "state_rules": {
                    "task_done": {"rule": "none", "new_state": "approved"},
                }
            }
        }
    }

    def states_for_kind(kind: str) -> list[str]:
        if kind == "request":
            return ["draft", "approved"]
        if kind == "task":
            return ["task_done"]
        return []

    errors = validate(config, states_for_kind)
    assert any("task_done" in e and "request" in e for e in errors)


def test_validate_skips_disabled_kind_state_rules() -> None:
    config = {
        "kinds": {
            "request": {
                "enabled": False,
                "state_rules": {
                    "task_done": {"rule": "ghost_rule", "new_state": "approved"},
                },
            }
        }
    }

    errors = validate(config, lambda kind: ["draft", "approved"])
    assert errors == []


def test_validate_unknown_rule_in_state_rules_reports_error() -> None:
    config = {
        "rules": {},
        "kinds": {
            "task": {
                "state_rules": {
                    "done": {"rule": "ghost_rule", "new_state": "done"},
                }
            }
        },
    }
    errors = validate(config, lambda kind: ["draft", "active", "done"])
    assert any("ghost_rule" in e for e in errors)


def test_validate_logs_warning_when_states_getter_raises(caplog) -> None:
    """Regression: a raising states_for_kind is logged, not silently swallowed.

    On failure valid_states falls back to empty, which flags every configured
    state invalid — a warning makes that fallback visible instead of confusing.
    """
    def boom(kind: str) -> list[str]:
        raise KeyError(kind)

    config = {
        "rules": {"none": {"enabled": True}},
        "kinds": {
            "task": {
                "state_rules": {"done": {"rule": "none", "new_state": "done"}},
            }
        },
    }

    logger_name = "audiagentic.foundation.workflow.propagation.propagation_config"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        validate(config, boom)

    assert any(
        "task" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    ), "raising states getter must log a warning"


def test_validate_no_states_getter_skips_state_check() -> None:
    # With no states_getter, unknown states are not checked — but unknown rules still are
    config = {
        "rules": {"none": {"enabled": True}},
        "kinds": {
            "task": {
                "state_rules": {
                    "phantom": {"rule": "none", "new_state": "done"},
                }
            }
        },
    }
    assert validate(config, None) == []
