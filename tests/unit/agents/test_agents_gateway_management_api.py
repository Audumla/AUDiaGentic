"""Unit tests for the generic gateway-management implementation API (SH11
Slice C). Mirrors tests/unit/planning/test_planning_api.py's config-related
coverage. Uses the real embedded/standalone/automatic descriptors -- no fake
registration needed, they are stable production config.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.management_api import (
    gateway_get_config,
    gateway_get_retention_policy,
    gateway_list_implementations,
    gateway_select_implementation,
    gateway_set_config,
    gateway_status,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(autouse=True)
def _force_feature_registry_repopulation():
    """Pre-existing test-infrastructure issue (AS76/TE02 step 10, not
    introduced here): foundation.features.registry's module-global
    ``_self_populate`` short-circuits once ANY component's implementations
    are registered, so under this repo's real conftest chain, whichever
    component's descriptors happened to load first in a pytest session can
    starve later ones -- confirmed this affects the pre-existing `planning`
    and `coding-lsp` components identically, not just `agents`.
    `planning`'s own tests work around it by registering a fake descriptor
    directly; this clears the whole registry and lets it repopulate from
    real config instead, since these tests exercise the real production
    embedded/standalone/automatic descriptors, not fakes."""
    from audiagentic.foundation.features.registry import clear

    clear()
    yield


def test_status_with_no_explicit_selection_reports_embedded_default(tmp_path: Path) -> None:
    status = gateway_status(tmp_path)
    assert status["implementation"] == "embedded"
    assert status["is_default"] is True


def test_list_implementations_includes_all_three(tmp_path: Path) -> None:
    result = gateway_list_implementations(tmp_path)
    assert set(result["implementations"].keys()) == {"embedded", "standalone", "automatic"}
    assert result["implementations"]["embedded"]["is_default"] is True
    assert result["implementations"]["standalone"]["is_default"] is False
    assert result["implementations"]["automatic"]["is_default"] is False


def test_select_implementation_persists_and_is_reflected_in_status(tmp_path: Path) -> None:
    result = gateway_select_implementation(tmp_path, "automatic")
    assert result["ok"] is True
    status = gateway_status(tmp_path)
    assert status["implementation"] == "automatic"
    assert status["enabled"] is True


def test_implementation_rollback_restores_previous_boundary(tmp_path: Path) -> None:
    gateway_select_implementation(tmp_path, "automatic")
    assert gateway_status(tmp_path)["implementation"] == "automatic"
    gateway_select_implementation(tmp_path, "embedded")
    restored = gateway_status(tmp_path)
    assert restored["implementation"] == "embedded"
    assert restored["enabled"] is True


def test_get_config_exposes_option_schema_for_automatic(tmp_path: Path) -> None:
    config = gateway_get_config(tmp_path, "automatic")
    assert config["implementation"] == "automatic"
    assert "startup-timeout-seconds" in config["schema"]
    assert config["config"]["startup-timeout-seconds"] == 30  # schema default


def test_get_config_exposes_option_schema_for_standalone(tmp_path: Path) -> None:
    config = gateway_get_config(tmp_path, "standalone")
    assert set(config["schema"].keys()) == {"endpoint", "token-file"}


def test_get_config_defaults_to_active_implementation(tmp_path: Path) -> None:
    gateway_select_implementation(tmp_path, "standalone")
    config = gateway_get_config(tmp_path)
    assert config["implementation"] == "standalone"


def test_set_config_persists_and_get_config_reflects_it(tmp_path: Path) -> None:
    gateway_set_config(tmp_path, "automatic", {"startup-timeout-seconds": 90})
    config = gateway_get_config(tmp_path, "automatic")
    assert config["config"]["startup-timeout-seconds"] == 90


def test_set_config_rejects_unknown_option(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        gateway_set_config(tmp_path, "automatic", {"not-a-real-option": 1})
    assert exc_info.value.code == "VAL-AGSV-028"


def test_set_config_rejects_wrong_type(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        gateway_set_config(tmp_path, "automatic", {"startup-timeout-seconds": "not-a-number"})
    assert exc_info.value.code == "VAL-AGSV-029"


def test_set_config_unknown_implementation_raises(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        gateway_set_config(tmp_path, "nonexistent-implementation", {})
    assert exc_info.value.code == "VAL-AGSV-027"


def test_set_config_never_adds_implementation_specific_tools() -> None:
    """Architecture guard for CREATING_A_COMPONENT.md's rule: no
    gateway-specific tool (e.g. a hardcoded automatic-only setter) exists
    on the management server -- get_config/set_config are the only
    settable surface."""
    admin_mcp_path = (
        Path(__file__).resolve().parents[3]
        / "src" / "audiagentic" / "components" / "agents" / "mcp" / "admin_mcp.py"
    )
    source = admin_mcp_path.read_text(encoding="utf-8")
    forbidden_patterns = [
        "def agent_gateway_set_automatic",
        "def agent_gateway_set_standalone",
        "def agent_gateway_set_embedded",
        "def set_open_mcp_gateway",
    ]
    hits = [p for p in forbidden_patterns if p in source]
    assert not hits, f"implementation-specific management tool(s) found: {hits}"


def test_retention_policy_projection_is_machine_owned_and_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_path = tmp_path / "machine-retention.json"
    policy_path.write_text(
        '{"policy-id":"ops","purge-enabled":true,'
        '"minimum-archive-age-seconds":3600,"max-batch-size":7,'
        '"secret-path":"must-not-leak"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))

    projection = gateway_get_retention_policy(tmp_path / "project")

    assert projection["available"] is True
    assert projection["purge-enabled"] is True
    assert projection["minimum-archive-age-seconds"] == 3600.0
    assert projection["max-batch-size"] == 7
    assert projection["policy-id"] == "ops"
    assert "secret-path" not in projection
    assert str(policy_path) not in str(projection)
