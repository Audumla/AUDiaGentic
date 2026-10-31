"""Admission-time node placement, before preparation or command construction.

The server owner supplies these IDs from its configured grants. This value is
not an effect grant; later NodeGrantAuthority admission validation may produce
it. CommandIdentity/SealedNodePlacement remain separate effect-time contracts.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import _identifier, _integer


@dataclass(frozen=True, slots=True)
class NodeAdmissionPlacement:
    server_id: str
    node_id: str
    workspace_id: str
    principal_id: str
    server_project_id: str
    grant_revision: int

    def __post_init__(self) -> None:
        for value in (
            self.server_id, self.node_id, self.workspace_id,
            self.principal_id, self.server_project_id,
        ):
            _identifier(value)
        _integer(self.grant_revision)

    def to_record_mapping(self) -> dict[str, str | int]:
        """Exact canonical admission tuple; server scope is owner-configured."""
        return {
            "node-id": self.node_id,
            "workspace-id": self.workspace_id,
            "principal-id": self.principal_id,
            "server-project-id": self.server_project_id,
            "grant-revision": self.grant_revision,
        }
