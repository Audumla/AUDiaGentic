"""Archive and purge executors with integrity and retention fences (SH24/SH26)."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.agents_paths import (
    gateway_request_dir,
    gateway_retention_lock_path,
    gateway_root,
)
from audiagentic.components.agents.gateway.session.retention import (
    _request_retention_pin_unlocked,
    request_retention_pin,
)
from audiagentic.components.agents.gateway.store import TERMINAL_STATES
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, read_text_with_retry
from audiagentic.foundation.system.process import StartupLock

from .retention_policy import load_retention_policy, policy_matches


class RequestAccess(Protocol):
    def get_execution_request(self, project_root: Path, request_id: str) -> dict[str, Any]: ...

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]: ...


def _root(operation: Mapping[str, Any]) -> Path:
    scope = operation.get("scope")
    raw = scope.get("project-root") if isinstance(scope, Mapping) else None
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise AudiaGenticError("VAL-AGM-008", "agents", "gateway operation requires absolute project-root", {})
    return Path(raw)


def _ids(operation: Mapping[str, Any]) -> list[str]:
    scope = operation.get("scope")
    raw = scope.get("request-ids") if isinstance(scope, Mapping) else None
    if not isinstance(raw, list) or not raw or any(not isinstance(x, str) or not x for x in raw):
        raise AudiaGenticError("VAL-AGM-008", "agents", "gateway operation requires request-ids", {})
    return list(dict.fromkeys(raw))


def _digest_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file() and child.name != "archive-manifest.json":
            digest.update(child.relative_to(path).as_posix().encode())
            digest.update(child.read_bytes())
    return digest.hexdigest()


class GatewayArchiveExecutor:
    def __init__(self, requests: RequestAccess) -> None:
        self._requests = requests

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        root = _root(operation)
        archive_root = gateway_root(root) / "archive"
        changed = 0
        blocked = 0
        for request_id in _ids(operation):
            record = self._requests.get_execution_request(root, request_id)
            if record.get("state") not in TERMINAL_STATES:
                blocked += 1
                continue
            source = gateway_request_dir(root, request_id)
            destination = archive_root / request_id
            manifest = destination / "archive-manifest.json"
            if manifest.is_file():
                changed += 0
                continue
            if not source.is_dir():
                blocked += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = archive_root / f".{request_id}.staging"
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(source, staging)
            tree_digest = _digest_tree(staging)
            staging.rename(destination)
            atomic_write_json(manifest, {
                "contract-version": "v1",
                "request-id": request_id,
                "record-digest": hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "archive-digest": tree_digest,
                "archived-at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })
            changed += 1
        return {"changed": changed, "blocked": blocked}


class GatewayPurgeExecutor:
    def __init__(self, requests: RequestAccess) -> None:
        self._requests = requests

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        root = _root(operation)
        scope = operation.get("scope")
        snapshot = scope.get("retention-policy") if isinstance(scope, Mapping) else None
        policy = load_retention_policy()
        if not policy.available or not policy.enabled or not isinstance(snapshot, dict) or not policy_matches(snapshot):
            return {"changed": 0, "blocked": len(_ids(operation)), "reason": "RETENTION_POLICY_UNAVAILABLE"}
        if len(_ids(operation)) > policy.max_batch_size:
            return {"changed": 0, "blocked": len(_ids(operation)), "reason": "RETENTION_BATCH_LIMIT"}
        changed = 0
        blocked = 0
        for request_id in _ids(operation):
            request_dir = gateway_request_dir(root, request_id)
            archive_dir = gateway_root(root) / "archive" / request_id
            # Purge is retry-safe: once both the live request and archived
            # copy are gone, a replay is an idempotent no-op.
            if not request_dir.exists() and not archive_dir.exists():
                continue
            record = self._requests.get_execution_request(root, request_id)
            if record.get("state") not in TERMINAL_STATES:
                blocked += 1
                continue
            if request_retention_pin(root, request_id).pinned:
                blocked += 1
                continue
            manifest = archive_dir / "archive-manifest.json"
            if not manifest.is_file():
                blocked += 1
                continue
            try:
                manifest_data = json.loads(read_text_with_retry(manifest))
                if not isinstance(manifest_data, dict) or manifest_data.get("archive-digest") != _digest_tree(archive_dir):
                    blocked += 1
                    continue
                archived_at = datetime.fromisoformat(str(manifest_data.get("archived-at", "")).replace("Z", "+00:00"))
                age_seconds = (datetime.now(timezone.utc) - archived_at).total_seconds()
                if age_seconds < policy.minimum_archive_age_seconds:
                    blocked += 1
                    continue
                current_digest = hashlib.sha256(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                if manifest_data.get("record-digest") != current_digest:
                    blocked += 1
                    continue
            except (OSError, ValueError, TypeError):
                blocked += 1
                continue
            # Re-read immediately before deletion: archive work is never an
            # authority. Every independently mutable fence is checked again:
            # machine policy can be withdrawn, request attempts can change,
            # archive contents can be altered, and a session pin can appear.
            # Pin creation and deletion share this fence. This closes the
            # census-to-delete race where a session could become referentially
            # pinned after the final read but before rmtree.
            with StartupLock(gateway_retention_lock_path(root)):
                if not policy_matches(snapshot):
                    blocked += 1
                    continue
                current_record = self._requests.get_execution_request(root, request_id)
                current_digest = hashlib.sha256(
                    json.dumps(current_record, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                if (
                    current_record.get("state") not in TERMINAL_STATES
                    or manifest_data.get("record-digest") != current_digest
                    or manifest_data.get("archive-digest") != _digest_tree(archive_dir)
                    or _request_retention_pin_unlocked(root, request_id).pinned
                ):
                    blocked += 1
                    continue
                removed = False
                if request_dir.exists():
                    shutil.rmtree(request_dir)
                    removed = True
                if archive_dir.exists():
                    shutil.rmtree(archive_dir)
                    removed = True
                if removed:
                    changed += 1
        return {"changed": changed, "blocked": blocked}


__all__ = ["GatewayArchiveExecutor", "GatewayPurgeExecutor"]
