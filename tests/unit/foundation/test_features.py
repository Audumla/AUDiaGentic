from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.features import registry
from audiagentic.foundation.features.lifecycle import (
    disable_feature,
    enable_feature,
    reset_feature_option,
    set_feature_option,
)
from audiagentic.foundation.features.loader import load_feature_from_yaml
from audiagentic.foundation.features.resolver import resolve_feature
from audiagentic.foundation.features.state import (
    get_component_state,
    get_feature_state,
    load_feature_state,
    migrate_to_shards,
    set_component_state,
)
from audiagentic.foundation.io import load_yaml_file


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_registry(isolated_features_registry) -> None:
    """Each test runs against an empty registry; prior state is restored after."""


def test_load_feature_descriptor_from_yaml(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "python.yaml",
        """
type: feature
parent: coding-lsp
kind: language
id: python
display-name: Python
dependencies:
  pyright:
    probe: binary:pyright-langserver
options-schema:
  type-checking-mode:
    type: enum
    values: [off, basic, strict]
    default: basic
""".strip(),
    )

    descriptor = load_feature_from_yaml(path)

    assert descriptor.parent == "coding-lsp"
    assert descriptor.kind == "language"
    assert descriptor.feature_id == "python"
    assert descriptor.dependencies["pyright"]["probe"] == "binary:pyright-langserver"
    assert descriptor.options_schema["type-checking-mode"].default == "basic"
    assert registry.get_feature("coding-lsp", "language", "python") == descriptor


def test_lifecycle_writes_feature_state_and_validates_options(tmp_path: Path) -> None:
    descriptor = load_feature_from_yaml(
        _write(
            tmp_path / "python.yaml",
            """
type: feature
parent: coding-lsp
kind: language
id: python
options-schema:
  type-checking-mode:
    type: enum
    values: [off, basic, strict]
    default: basic
""".strip(),
        )
    )

    assert enable_feature(tmp_path, "coding-lsp", "language", "python")["ok"] is True
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").enabled is True

    bad = set_feature_option(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        "type-checking-mode",
        "aggressive",
    )
    assert bad["ok"] is False
    assert "expected one of" in bad["error"]

    good = set_feature_option(
        tmp_path,
        "coding-lsp",
        "language",
        "python",
        "type-checking-mode",
        "strict",
    )
    assert good["ok"] is True
    resolved = resolve_feature(tmp_path, descriptor)
    assert resolved.effective_options["type-checking-mode"] == "strict"

    assert reset_feature_option(tmp_path, "coding-lsp", "language", "python", "type-checking-mode")["removed"] is True
    assert resolve_feature(tmp_path, descriptor).effective_options["type-checking-mode"] == "basic"

    assert disable_feature(tmp_path, "coding-lsp", "language", "python")["enabled"] is False


def test_component_options_do_not_pollute_unrelated_feature_options(tmp_path: Path) -> None:
    descriptor = load_feature_from_yaml(
        _write(
            tmp_path / "python.yaml",
            """
type: feature
parent: coding-lsp
kind: language
id: python
options-schema:
  type-checking-mode:
    type: enum
    values: [basic, strict]
    default: basic
""".strip(),
        )
    )
    _write(
        tmp_path / ".audiagentic" / "config" / "runtime" / "features.yaml",
        """
coding-lsp:
  options:
    max-diagnostics: 500
  features:
    language:
      python:
        enabled: true
""".strip(),
    )

    resolved = resolve_feature(tmp_path, descriptor)

    assert resolved.component_options == {"max-diagnostics": 500}
    assert resolved.effective_options == {"type-checking-mode": "basic"}


def test_register_all_components_dispatches_feature_yaml_without_changing_components(tmp_path: Path) -> None:
    _write(
        tmp_path / "project.yaml",
        """
type: component
id: project
display-name: Project
description: Project component
detection-marker: .audiagentic/components/project.yaml
""".strip(),
    )
    _write(
        tmp_path / "python.yaml",
        """
type: feature
parent: coding-lsp
kind: language
id: python
""".strip(),
    )

    descriptors = register_all_components([tmp_path])

    assert [descriptor.component_id for descriptor in descriptors] == ["project"]
    assert registry.get_feature("coding-lsp", "language", "python") is not None


def test_feature_state_is_saved_under_runtime_config(tmp_path: Path) -> None:
    load_feature_from_yaml(
        _write(
            tmp_path / "python.yaml",
            """
type: feature
parent: coding-lsp
kind: language
id: python
""".strip(),
        )
    )

    enable_feature(tmp_path, "coding-lsp", "language", "python")

    # State is now sharded per component: features/{parent}.yaml.
    shard = tmp_path / ".audiagentic" / "config" / "runtime" / "features" / "coding-lsp.yaml"
    assert shard.exists()
    # Legacy monolithic file is not written by mutations.
    assert not (tmp_path / ".audiagentic" / "config" / "runtime" / "features.yaml").exists()

    state = load_feature_state(tmp_path)
    assert state["coding-lsp"]["features"]["language:python"]["enabled"] is True


def test_migrate_to_shards_splits_legacy_file_with_flat_migration(tmp_path: Path) -> None:
    legacy = tmp_path / ".audiagentic" / "config" / "runtime" / "features.yaml"
    _write(
        legacy,
        """
coding-lsp:
  features:
    language:
      python:
        enabled: true
providers:
  implementations:
    claude:
      enabled: true
      features:
        mcp:
          mcp:
            enabled: true
""".strip(),
    )

    migrated = migrate_to_shards(tmp_path)

    assert set(migrated) == {"coding-lsp", "providers"}

    shard_dir = tmp_path / ".audiagentic" / "config" / "runtime" / "features"
    coding = load_yaml_file(shard_dir / "coding-lsp.yaml")
    providers = load_yaml_file(shard_dir / "providers.yaml")

    # Nested -> flat composite keys applied per shard.
    assert coding["features"]["language:python"]["enabled"] is True
    assert providers["implementations"]["claude"]["features"]["mcp:mcp"]["enabled"] is True

    # Legacy file renamed, not deleted.
    assert not legacy.exists()
    assert legacy.with_suffix(".yaml.migrated").exists()


def test_set_component_state_isolation_does_not_rewrite_sibling_shard(tmp_path: Path) -> None:
    set_component_state(tmp_path, "comp-a", {"features": {"x:1": {"enabled": True}}})
    shard_a = tmp_path / ".audiagentic" / "config" / "runtime" / "features" / "comp-a.yaml"
    before = shard_a.read_bytes()

    # Writing component B must not touch component A's shard.
    set_component_state(tmp_path, "comp-b", {"features": {"y:2": {"enabled": True}}})

    assert shard_a.read_bytes() == before
    shard_b = tmp_path / ".audiagentic" / "config" / "runtime" / "features" / "comp-b.yaml"
    assert shard_b.exists()
    assert get_component_state(tmp_path, "comp-a") == {"features": {"x:1": {"enabled": True}}}
