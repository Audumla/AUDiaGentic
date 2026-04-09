from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DocumentationSurface:
    id: str
    path: str
    kind: str
    mode: str
    profile: str
    update_policy: str
    entry: bool = False
    seed_on_install: bool = False


class DocumentationManager:
    """Resolve configured documentation surfaces and required sync operations."""

    def __init__(self, root: Path, config: dict[str, Any]):
        self.root = root
        self.config = config

    def list_surfaces(self) -> list[DocumentationSurface]:
        doc_cfg = self.config.get("planning", {}).get("documentation", {})
        return [DocumentationSurface(**item) for item in doc_cfg.get("surfaces", [])]

    def get_surface(self, surface_id: str) -> DocumentationSurface | None:
        for surface in self.list_surfaces():
            if surface.id == surface_id:
                return surface
        return None

    def pending_updates_for_kind(
        self, kind: str, profile_pack: dict[str, Any]
    ) -> list[str]:
        return (
            profile_pack.get("documentation", {})
            .get("required_updates", {})
            .get(kind, [])
        )

    def profile_pack_required_updates(
        self, profile_pack: dict[str, Any]
    ) -> dict[str, list[str]]:
        return profile_pack.get("documentation", {}).get("required_updates", {})

