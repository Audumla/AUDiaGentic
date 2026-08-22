"""Public Agents configuration application boundary."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import AgentsConfigDocument
from .repository import AgentsConfigRepository, AgentsConfigSnapshot
from .resolution import resolve_agent
from audiagentic.components.agents.agents_paths import global_agents_config_path


class AgentsConfigService:
    """Machine-global configuration operations for protocol adapters."""

    def __init__(self, repository: AgentsConfigRepository | None = None) -> None:
        # The hosted agent catalog is machine-global.  ``root`` is retained on
        # methods for protocol compatibility, but cannot select a project-local
        # authority accidentally.
        self._repository = repository or AgentsConfigRepository(
            global_agents_config_path(), required=True
        )

    def read(self, root: Path) -> AgentsConfigSnapshot:
        return self._repository.read(root)

    def validate(self, document: AgentsConfigDocument) -> tuple[str, ...]:
        return self._repository.validate(document)

    def apply(self, root: Path, document: AgentsConfigDocument, *, expected_digest: str | None) -> AgentsConfigSnapshot:
        return self._repository.replace(root, document, expected_digest=expected_digest)

    def put(self, root: Path, kind: str, item: dict[str, Any], *, expected_digest: str) -> AgentsConfigSnapshot:
        return self._repository.put(root, kind, item, expected_digest=expected_digest)

    def delete(self, root: Path, kind: str, item_id: str, *, expected_digest: str) -> AgentsConfigSnapshot:
        return self._repository.delete(root, kind, item_id, expected_digest=expected_digest)

    def get(self, root: Path, kind: str, item_id: str) -> dict[str, Any]:
        return self._repository.get(root, kind, item_id)

    def resolve(self, root: Path, agent_id: str) -> dict[str, Any]:
        return resolve_agent(self.read(root).document, agent_id)

    def triggers(self, root: Path) -> tuple[dict[str, Any], ...]:
        """Return validated project-owned trigger definitions."""
        return self.read(root).document.triggers
