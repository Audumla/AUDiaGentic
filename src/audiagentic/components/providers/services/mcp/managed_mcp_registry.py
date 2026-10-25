"""Durable provider MCP ownership, raw-entry proofs and prepared native transitions."""

from __future__ import annotations

import json
import re
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.toolchains.config.managed_config import ManagedFragmentRegistry

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _valid_owners(rows: object) -> bool:
    return isinstance(rows, dict) and all(
        isinstance(scope, str)
        and isinstance(entries, dict)
        and all(isinstance(mid, str) and isinstance(name, str) for mid, name in entries.items())
        for scope, entries in rows.items()
    )


def _valid_proofs(proofs: object) -> bool:
    return isinstance(proofs, dict) and all(
        isinstance(scope, str)
        and isinstance(proof, dict)
        and isinstance(proof.get("target"), str)
        and isinstance(proof.get("entries"), dict)
        and all(
            isinstance(mid, str) and isinstance(value, str) and _SHA256.fullmatch(value)
            for mid, value in proof["entries"].items()
        )
        for scope, proof in proofs.items()
    )


class McpOwnershipRegistry(ManagedFragmentRegistry):
    """Single v2 registry; a prepared transition never grants ownership by itself."""

    def __init__(self, root: Path):
        super().__init__(
            root,
            "managed-mcp-servers.json",
            top_level_key="providers",
            contract_version="v2",
            storage_path=root / ".audiagentic/state/providers/managed-mcp-servers.json",
        )
        self.root = root.resolve()
        self.legacy_path = root / ".audiagentic/runtime/providers/managed-mcp-servers.json"

    def _validate(self, data: dict) -> None:
        if data.get("contract-version") not in {"v1", "v2"}:
            raise ValueError("unknown contract")
        if not _valid_owners(data.get("providers")) or not _valid_proofs(data.get("proofs", {})):
            raise ValueError("invalid MCP owners or raw-entry proofs")
        prepared = data.get("prepared", {})
        if not isinstance(prepared, dict) or len(prepared) > 1:
            raise ValueError("invalid prepared transition count")
        if prepared and data["contract-version"] != "v2":
            raise ValueError("prepared transition requires v2")
        for scope, record in prepared.items():
            if not isinstance(scope, str) or not isinstance(record, dict) or set(record) != {
                "target", "scope", "provider_id", "pre_hash", "post_hash",
                "before_hash", "owners_after", "proofs_after",
            }:
                raise ValueError("invalid prepared transition shape")
            provider = record["provider_id"]
            if not isinstance(provider, str) or not provider or scope != record["scope"] or not scope.startswith(provider + "/"):
                raise ValueError("invalid prepared scope identity")
            target = record["target"]
            if not isinstance(target, str):
                raise ValueError("invalid prepared target")
            resolved = Path(target).resolve()
            if str(resolved) != target or not resolved.is_relative_to(self.root) or resolved == self.root:
                raise ValueError("prepared target escapes canonical project")
            if (
                record["pre_hash"] != "absent"
                and (not isinstance(record["pre_hash"], str) or not _SHA256.fullmatch(record["pre_hash"]))
            ):
                raise ValueError("invalid prepared pre-hash")
            if any(
                not isinstance(record[key], str) or not _SHA256.fullmatch(record[key])
                for key in ("post_hash", "before_hash")
            ):
                raise ValueError("invalid prepared post/authority hash")
            if not _valid_owners(record["owners_after"]) or not _valid_proofs(record["proofs_after"]):
                raise ValueError("invalid prepared ownership/proofs")
            proof = record["proofs_after"].get(scope)
            if record["owners_after"].get(scope) and (
                not proof or proof["target"] != target
                or set(proof["entries"]) != set(record["owners_after"][scope])
            ):
                raise ValueError("prepared scope proof mismatch")

    def document(self) -> dict:
        path = self.path if self.path.exists() else self.legacy_path
        if not path.exists():
            return {"contract-version": "v2", "providers": {}, "proofs": {}}
        try:
            data = json.loads(path.read_text(encoding="utf8"))
            if not isinstance(data, dict):
                raise ValueError("invalid registry document")
            self._validate(data)
            # v1 is a migration source only. Once v2 exists it is authoritative;
            # a crash after v2 commit but before retiring v1 cannot revert it.
            if self.path.exists() and self.legacy_path.exists():
                old = json.loads(self.legacy_path.read_text(encoding="utf8"))
                if old.get("contract-version") == "v2" and old.get("providers") != data["providers"]:
                    raise ValueError("conflicting v2 ownership authorities")
            return data
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise AudiaGenticError(
                code="CON-PMCP-002", kind="providers",
                message="MCP ownership requires reconciliation",
            ) from exc

    def load(self) -> dict[str, dict[str, str]]:
        data = self.document()
        if data.get("prepared"):
            raise AudiaGenticError(
                code="CON-PMCP-002", kind="providers",
                message="Prepared native MCP transition requires guarded recovery",
            )
        return data["providers"]

    def write_document(self, data: dict) -> bool:
        """One atomic owners/proofs/prepared commit; skip exact logical no-ops."""
        self._validate(data)
        before = self.document()
        if before == data and self.path.exists():
            return False
        atomic_write_json(self.path, data)
        # Legacy is only retired after the v2 commit; a crash before unlink is safe.
        if self.legacy_path.exists():
            self.legacy_path.unlink()
        return True

    def save(self, owners: dict[str, dict[str, str]]) -> None:
        if not _valid_owners(owners):
            raise ValueError("Invalid MCP ownership mapping")
        data = self.document()
        if data.get("prepared"):
            raise AudiaGenticError(
                code="CON-PMCP-002", kind="providers",
                message="Prepared native MCP transition requires guarded recovery",
            )
        data.update({"contract-version": "v2", "providers": owners})
        self.write_document(data)

    def save_proofs(self, scope: str, proof: dict) -> None:
        data = self.document()
        if data.get("prepared"):
            raise AudiaGenticError(
                code="CON-PMCP-002", kind="providers",
                message="Prepared native MCP transition requires guarded recovery",
            )
        data.setdefault("proofs", {})[scope] = proof
        data["contract-version"] = "v2"
        self.write_document(data)


def mcp_ownership_registry(project_root: Path) -> McpOwnershipRegistry:
    return McpOwnershipRegistry(project_root)


def _registry_path(project_root: Path) -> Path:
    return mcp_ownership_registry(project_root).path


def load_managed_mcp_registry(project_root: Path) -> dict[str, dict[str, str]]:
    return mcp_ownership_registry(project_root).load()


def save_managed_mcp_registry(project_root: Path, registry: dict[str, dict[str, str]]) -> None:
    mcp_ownership_registry(project_root).save(registry)
