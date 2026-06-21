from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.features import registry
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.lifecycle import (
    disable_implementation_feature,
    enable_implementation_feature,
    set_implementation_feature_option,
)
from audiagentic.foundation.features.loader import register_from_yaml
from audiagentic.foundation.features.state import (
    get_implementation_feature_state,
    set_implementation_state,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def setup_function() -> None:
    registry.clear()


def teardown_function() -> None:
    registry.clear()


_MCP_FEATURE = """
type: feature
parent: providers
implementation: {impl}
kind: mcp
id: mcp
options-schema:
  transport:
    type: enum
    values: [stdio, http]
    default: stdio
"""


def _register_two(tmp_path: Path) -> None:
    register_from_yaml(_write(tmp_path / "claude.mcp.yaml", _MCP_FEATURE.format(impl="claude")))
    register_from_yaml(_write(tmp_path / "codex.mcp.yaml", _MCP_FEATURE.format(impl="codex")))


def test_same_kind_id_across_implementations_does_not_collide(tmp_path: Path) -> None:
    _register_two(tmp_path)

    claude = registry.get_implementation_feature("providers", "claude", "mcp", "mcp")
    codex = registry.get_implementation_feature("providers", "codex", "mcp", "mcp")

    assert claude is not None and claude.implementation == "claude"
    assert codex is not None and codex.implementation == "codex"
    # Shared-feature registry is untouched by implementation-scoped registration.
    assert registry.get_feature("providers", "mcp", "mcp") is None


def test_get_implementation_features_scopes_to_one_implementation(tmp_path: Path) -> None:
    _register_two(tmp_path)

    claude_features = registry.get_implementation_features("providers", "claude")
    assert set(claude_features) == {"mcp"}


def test_enable_persists_under_implementation_and_isolated(tmp_path: Path) -> None:
    _register_two(tmp_path)

    enable_implementation_feature(tmp_path, "providers", "claude", "mcp", "mcp")

    assert get_implementation_feature_state(tmp_path, "providers", "claude", "mcp", "mcp").enabled is True
    # Sibling implementation's same-named feature is unaffected.
    assert get_implementation_feature_state(tmp_path, "providers", "codex", "mcp", "mcp").enabled is False

    disable_implementation_feature(tmp_path, "providers", "claude", "mcp", "mcp")
    assert get_implementation_feature_state(tmp_path, "providers", "claude", "mcp", "mcp").enabled is False


def test_set_implementation_state_preserves_nested_feature_state(tmp_path: Path) -> None:
    _register_two(tmp_path)
    enable_implementation_feature(tmp_path, "providers", "claude", "mcp", "mcp")

    # Toggling implementation-level enabled must not wipe nested feature state.
    set_implementation_state(tmp_path, "providers", "claude", ImplementationState(enabled=True))

    assert get_implementation_feature_state(tmp_path, "providers", "claude", "mcp", "mcp").enabled is True


def test_option_validates_and_persists(tmp_path: Path) -> None:
    _register_two(tmp_path)

    ok = set_implementation_feature_option(tmp_path, "providers", "claude", "mcp", "mcp", "transport", "http")
    assert ok["ok"] is True
    assert get_implementation_feature_state(tmp_path, "providers", "claude", "mcp", "mcp").options["transport"] == "http"

    bad = set_implementation_feature_option(tmp_path, "providers", "claude", "mcp", "mcp", "transport", "carrier-pigeon")
    assert bad["ok"] is False
