"""Caller identity is resolved locally and cannot redirect recipient execution."""
from dataclasses import replace
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.node.source_workspace import (
    resolve_caller_workspace,
    validate_recipient_workspace,
)
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayNodeConfig,
    SharedGatewayNodeWorkspace,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def configured(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    config = SharedGatewayNodeConfig(
        "node", "server", "wss://localhost/node", tmp_path / "token", tmp_path / "state",
        {"workspace": SharedGatewayNodeWorkspace(root, frozenset({"profile"}))},
    )
    return config, root


def test_source_matches_actual_caller_and_recipient_local_binding(configured):
    config, root = configured
    source = resolve_caller_workspace(config, root)
    assert source.identity.source_node_id == "node"
    assert source.identity.workspace_id == "workspace"
    assert source.identity.access_mode == "read-write"
    assert validate_recipient_workspace(config, source.identity, caller_root=str(root)) == source
    assert str(root) not in repr(source)


def test_unconfigured_or_ambiguous_caller_never_uses_first_workspace(configured, tmp_path):
    config, root = configured
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(AudiaGenticError, match="unique configured"):
        resolve_caller_workspace(config, other)
    duplicate = replace(config, workspaces={**config.workspaces, "alias": config.workspaces["workspace"]})
    with pytest.raises(AudiaGenticError, match="unique configured"):
        resolve_caller_workspace(duplicate, root)


def test_foreign_source_rejects_before_path_resolution_even_if_text_matches(configured, monkeypatch):
    config, root = configured
    foreign = replace(resolve_caller_workspace(config, root).identity, source_node_id="other-node")
    def forbidden(*args, **kwargs):
        pytest.fail("foreign path must not be resolved on recipient")
    monkeypatch.setattr(Path, "resolve", forbidden)
    with pytest.raises(AudiaGenticError, match="Remote caller"):
        validate_recipient_workspace(config, foreign, caller_root=str(root))


def test_read_only_label_is_not_an_enforcement_capability(configured):
    config, root = configured
    source = replace(resolve_caller_workspace(config, root).identity, access_mode="read-only")
    with pytest.raises(AudiaGenticError, match="enforcement mode"):
        validate_recipient_workspace(config, source, caller_root=str(root))


@pytest.mark.parametrize("change", ["workspace", "root", "profile", "digest"])
def test_local_binding_drift_cannot_silently_retarget(configured, tmp_path, change):
    config, root = configured
    source = resolve_caller_workspace(config, root).identity
    other = tmp_path / "other"
    other.mkdir()
    if change == "workspace":
        source = replace(source, workspace_id="unknown")
    elif change == "root":
        config = replace(config, workspaces={"workspace": SharedGatewayNodeWorkspace(other, frozenset({"profile"}))})
    elif change == "profile":
        config = replace(config, workspaces={"workspace": SharedGatewayNodeWorkspace(root, frozenset({"different"}))})
    else:
        source = replace(source, binding_sha256="a" * 64)
    with pytest.raises(AudiaGenticError):
        validate_recipient_workspace(config, source, caller_root=str(root))


def test_another_caller_root_cannot_be_an_execution_override(configured, tmp_path):
    config, root = configured
    source = resolve_caller_workspace(config, root).identity
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(AudiaGenticError):
        validate_recipient_workspace(config, source, caller_root=str(other))
    with pytest.raises(AudiaGenticError):
        resolve_caller_workspace(config, Path("relative"))


def test_no_worktree_or_environment_is_created_for_missing_root(configured):
    config, root = configured
    missing = root / "missing"
    with pytest.raises(AudiaGenticError):
        resolve_caller_workspace(config, missing)
    assert not missing.exists()
