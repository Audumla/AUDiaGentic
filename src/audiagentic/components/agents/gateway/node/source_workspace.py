"""Resolve caller workspace locally; never discover or provision remote files.

The stdio owner and execution node use the same configured-root identity. The
gateway only retains the private locator and authenticates source enrollment.
These values do not authenticate a machine or create a workspace grant.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.components.agents.contracts.execution_context import canonicalize_project_root
from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig

from .admission_contract import SourceWorkspaceIdentity
from .contracts import canonical_json, conflict, invalid


@dataclass(frozen=True)
class LocalSourceWorkspace:
    identity: SourceWorkspaceIdentity
    root: Path = field(repr=False)


def resolve_caller_workspace(config: SharedGatewayNodeConfig, caller_root: Path) -> LocalSourceWorkspace:
    """Match the actual local caller root to exactly one enrolled workspace.

    Called only on the caller machine, never by the central gateway. There is
    no fallback to the first workspace, recipient config or process directory.
    """
    if type(config) is not SharedGatewayNodeConfig or not isinstance(caller_root, Path) or not caller_root.is_absolute():
        raise invalid(1, "Caller workspace requires local node configuration and an absolute root")
    try:
        root = caller_root.resolve(strict=True)
        if not root.is_dir():
            raise OSError
        canonical = canonicalize_project_root(str(root))
        matches = []
        for workspace_id, workspace in config.workspaces.items():
            if not workspace.root.is_absolute():
                raise invalid(1, "Configured source workspace root must be absolute")
            local = workspace.root.resolve(strict=True)
            if not local.is_dir():
                raise OSError
            if canonicalize_project_root(str(local)).fingerprint == canonical.fingerprint:
                matches.append((workspace_id, workspace))
        if len(matches) != 1:
            raise conflict(1, "Caller workspace has no unique configured local binding")
        workspace_id, workspace = matches[0]
        binding = hashlib.sha256(canonical_json({
            "version": 1, "node-id": config.node_id, "workspace-id": workspace_id,
            "root-fingerprint": canonical.fingerprint,
            "execution-profiles": sorted(workspace.execution_profiles),
        })).hexdigest()
        return LocalSourceWorkspace(
            SourceWorkspaceIdentity(1, config.node_id, workspace_id, "read-write", binding), root,
        )
    except (OSError, RuntimeError, ValueError):
        raise conflict(1, "Caller workspace local binding is unavailable") from None


def validate_recipient_workspace(
    config: SharedGatewayNodeConfig, source: SourceWorkspaceIdentity, *, caller_root: str,
) -> LocalSourceWorkspace:
    """Revalidate locally after source authentication, before preparation/effect.

    The caller path is compared with the recipient's configured binding; it is
    never accepted as an execution-directory override. Initial writable routing
    is same-node only. Read-only declarations cannot substitute for enforcement.
    """
    if type(config) is not SharedGatewayNodeConfig or type(source) is not SourceWorkspaceIdentity:
        raise invalid(1, "Recipient workspace requires typed local configuration and source identity")
    if source.source_node_id != config.node_id:
        raise conflict(1, "Remote caller workspace access is not implemented")
    if source.access_mode != "read-write":
        raise conflict(1, "Read-only node execution requires a qualified enforcement mode")
    if source.workspace_id not in config.workspaces:
        raise conflict(1, "Source workspace is not configured on this recipient")
    if not isinstance(caller_root, str) or not caller_root:
        raise invalid(1, "Caller workspace locator must be private local path text")
    actual = resolve_caller_workspace(config, Path(caller_root))
    if actual.identity != source:
        raise conflict(1, "Caller workspace differs from recipient local binding")
    return actual


__all__ = ["LocalSourceWorkspace", "resolve_caller_workspace", "validate_recipient_workspace"]
