"""Single-file, validated, compare-and-swap Agents configuration repository."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import agents_config_path
from audiagentic.components.agents.configuration.contracts import (
    AgentsConfigDocument,
    ConfigKind,
)
from audiagentic.components.agents.configuration.validation import validate_document
from audiagentic.foundation.io import load_yaml_file, save_yaml_file
from audiagentic.foundation.system.process import StartupLock


class AgentsConfigConflictError(RuntimeError):
    """Raised when a compare-and-swap mutation sees a changed document."""


class AgentsConfigValidationError(ValueError):
    """Raised when the canonical document violates its cross-reference rules."""


@dataclass(frozen=True, slots=True)
class AgentsConfigSnapshot:
    document: AgentsConfigDocument
    digest: str


class AgentsConfigRepository:
    def read(self, project_root: Path) -> AgentsConfigSnapshot:
        path = agents_config_path(project_root)
        data = load_yaml_file(path) if path.exists() else {}
        document = AgentsConfigDocument.from_mapping(data)
        self._validate_document(document)
        return AgentsConfigSnapshot(document, _digest(document))

    def validate(self, document: AgentsConfigDocument) -> tuple[str, ...]:
        issues = list(validate_document(document))
        if document.contract_version != "v2":
            issues.append("contract-version must be v2")
        return tuple(sorted(issues))

    def replace(self, project_root: Path, document: AgentsConfigDocument, *, expected_digest: str | None) -> AgentsConfigSnapshot:
        issues = self.validate(document)
        if issues:
            raise AgentsConfigValidationError("; ".join(issues))
        path = agents_config_path(project_root)
        lock = path.with_name("agents.yaml.lock")
        with StartupLock(lock):
            current = self.read(project_root) if path.exists() else None
            if current is None:
                if expected_digest is not None:
                    raise AgentsConfigConflictError("Agents config was created concurrently")
            elif expected_digest is None or expected_digest != current.digest:
                raise AgentsConfigConflictError("Agents config digest changed")
            save_yaml_file(path, document.to_mapping(), sort_keys=False, atomic=True)
        return AgentsConfigSnapshot(document, _digest(document))

    def get(self, project_root: Path, kind: ConfigKind, item_id: str) -> dict[str, Any]:
        """Return one canonical record by collection kind and stable id."""
        snapshot = self.read(project_root)
        key = {"prompt": "prompt_id", "role": "role_id", "execution_profile": "profile_id", "agent": "agent_id", "trigger": "trigger_id"}.get(kind)
        if key is None:
            raise KeyError(f"unknown config kind: {kind}")
        values = getattr(snapshot.document, {"prompt": "prompts", "role": "roles", "execution_profile": "execution_profiles", "agent": "agents", "trigger": "triggers"}[kind])
        for value in values:
            mapping = value.to_dict() if hasattr(value, "to_dict") else value
            if mapping.get(key, mapping.get(key.replace("_", "-"))) == item_id:
                return dict(mapping)
        raise KeyError(item_id)

    def put(
        self,
        project_root: Path,
        kind: ConfigKind,
        item: dict[str, Any],
        *,
        expected_digest: str,
    ) -> AgentsConfigSnapshot:
        """Replace or insert one record, validating the complete document."""
        snapshot = self.read(project_root)
        collections = {
            "prompt": "prompts", "role": "roles", "execution_profile": "execution_profiles", "agent": "agents", "trigger": "triggers"
        }
        collection = collections.get(kind)
        if collection is None:
            raise KeyError(f"unknown config kind: {kind}")
        key = {"prompt": "prompt_id", "role": "role_id", "execution_profile": "profile_id", "agent": "agent_id", "trigger": "trigger_id"}[kind]
        values = list(getattr(snapshot.document, collection))
        item_id = item.get(key, item.get(key.replace("_", "-")))
        for index, existing in enumerate(values):
            if existing.get(key, existing.get(key.replace("_", "-"))) == item_id:
                values[index] = dict(item)
                break
        else:
            values.append(dict(item))
        document = AgentsConfigDocument(
            snapshot.document.contract_version,
            snapshot.document.prompts if collection != "prompts" else tuple(values),
            snapshot.document.roles if collection != "roles" else tuple(values),
            snapshot.document.execution_profiles if collection != "execution_profiles" else tuple(values),
            snapshot.document.agents if collection != "agents" else tuple(values),
            snapshot.document.triggers if collection != "triggers" else tuple(values),
        )
        return self.replace(project_root, document, expected_digest=expected_digest)

    def delete(self, project_root: Path, kind: ConfigKind, item_id: str, *, expected_digest: str) -> AgentsConfigSnapshot:
        snapshot = self.read(project_root)
        collections = {"prompt": "prompts", "role": "roles", "execution_profile": "execution_profiles", "agent": "agents", "trigger": "triggers"}
        collection = collections.get(kind)
        if collection is None:
            raise KeyError(f"unknown config kind: {kind}")
        key = {"prompt": "prompt_id", "role": "role_id", "execution_profile": "profile_id", "agent": "agent_id", "trigger": "trigger_id"}[kind]
        values = tuple(value for value in getattr(snapshot.document, collection) if value.get(key, value.get(key.replace("_", "-"))) != item_id)
        if len(values) == len(getattr(snapshot.document, collection)):
            raise KeyError(item_id)
        document = AgentsConfigDocument(
            snapshot.document.contract_version,
            snapshot.document.prompts if collection != "prompts" else values,
            snapshot.document.roles if collection != "roles" else values,
            snapshot.document.execution_profiles if collection != "execution_profiles" else values,
            snapshot.document.agents if collection != "agents" else values,
            snapshot.document.triggers if collection != "triggers" else values,
        )
        return self.replace(project_root, document, expected_digest=expected_digest)

    def _validate_document(self, document: AgentsConfigDocument) -> None:
        issues = self.validate(document)
        if issues:
            raise AgentsConfigValidationError("; ".join(issues))


def _id(item: dict[str, Any], *keys: str) -> str:
    return str(next((item.get(key) for key in keys if item.get(key) is not None), ""))


def _digest(document: AgentsConfigDocument) -> str:
    raw = json.dumps(document.to_mapping(), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
