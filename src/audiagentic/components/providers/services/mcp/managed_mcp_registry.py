"""Track AUDiaGentic-owned provider MCP entries by stable managed id."""

from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.toolchains.config.managed_config import ManagedFragmentRegistry


class McpOwnershipRegistry(ManagedFragmentRegistry):
    """One durable MCP authority, with a bounded runtime-v1 migration."""

    def __init__(self, root: Path):
        super().__init__(
            root,
            "managed-mcp-servers.json",
            top_level_key="providers",
            contract_version="v2",
            storage_path=root / ".audiagentic/state/providers/managed-mcp-servers.json",
        )
        self.legacy_path = root / ".audiagentic/runtime/providers/managed-mcp-servers.json"

    def document(self) -> dict:
        path = self.path if self.path.exists() else self.legacy_path
        if not path.exists():
            return {"contract-version": "v2", "providers": {}, "proofs": {}}
        try:
            data = json.loads(path.read_text(encoding="utf8"))
            if data.get("contract-version") not in {"v1", "v2"}:
                raise ValueError("unknown contract")
            if not isinstance(data.get("providers"), dict):
                raise ValueError("invalid ownership")
            if any(
                not isinstance(rows, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in rows.items())
                for rows in data["providers"].values()
            ):
                raise ValueError("invalid ownership entry")
            proofs = data.get("proofs", {})
            if not isinstance(proofs, dict) or any(
                not isinstance(scope, str)
                or not isinstance(proof, dict)
                or not isinstance(proof.get("target"), str)
                or not isinstance(proof.get("entries"), dict)
                or any(
                    not isinstance(k, str) or not isinstance(v, str)
                    for k, v in proof["entries"].items()
                )
                for scope, proof in proofs.items()
            ):
                raise ValueError("invalid ownership proofs")
            if self.path.exists() and self.legacy_path.exists():
                old = json.loads(self.legacy_path.read_text(encoding="utf8"))
                if old.get("providers") != data["providers"]:
                    raise ValueError("conflicting ownership authorities")
            return data
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise AudiaGenticError(
                code="CON-PMCP-002",
                kind="providers",
                message="MCP ownership requires reconciliation",
            ) from exc

    def load(self) -> dict[str, dict[str, str]]:
        return self.document()["providers"]

    def save(self, owners: dict[str, dict[str, str]]) -> None:
        if not isinstance(owners, dict) or any(
            not isinstance(scope, str)
            or not isinstance(rows, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in rows.items())
            for scope, rows in owners.items()
        ):
            raise ValueError("Invalid MCP ownership mapping")
        data = self.document()
        data.update({"contract-version": "v2", "providers": owners})
        atomic_write_json(self.path, data)
        if self.legacy_path.exists():
            self.legacy_path.unlink()

    def save_proofs(self, scope: str, proof: dict) -> None:
        data = self.document()
        if data.get("proofs", {}).get(scope) == proof and self.path.exists():
            return
        data.setdefault("proofs", {})[scope] = proof
        data["contract-version"] = "v2"
        atomic_write_json(self.path, data)


def mcp_ownership_registry(project_root: Path) -> McpOwnershipRegistry:
    """The one MCP-scoped instance of the foundation ManagedFragmentRegistry."""
    return McpOwnershipRegistry(project_root)


def _registry_path(project_root: Path) -> Path:
    return mcp_ownership_registry(project_root).path


def load_managed_mcp_registry(project_root: Path) -> dict[str, dict[str, str]]:
    return mcp_ownership_registry(project_root).load()


def save_managed_mcp_registry(project_root: Path, registry: dict[str, dict[str, str]]) -> None:
    mcp_ownership_registry(project_root).save(registry)
