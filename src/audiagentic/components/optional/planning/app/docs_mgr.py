from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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


@dataclass
class DocumentCollection:
    id: str
    path: str
    format: str
    output: dict[str, dict[str, Any]]
    include: str = "*.md"
    filters: dict[str, dict[str, Any]] | None = None


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

    def list_collections(self) -> list[DocumentCollection]:
        doc_cfg = self.config.get("planning", {}).get("documentation", {})
        return [DocumentCollection(**item) for item in doc_cfg.get("collections", [])]

    def get_collection(self, collection_id: str) -> DocumentCollection | None:
        for collection in self.list_collections():
            if collection.id == collection_id:
                return collection
        return None

    def _frontmatter(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        try:
            _, fm, _ = text.split("---", 2)
        except ValueError:
            return {}
        return yaml.safe_load(fm) or {}

    def _resolve_spec_value(
        self,
        spec: dict[str, Any],
        path: Path,
        frontmatter: dict[str, Any] | None,
    ) -> Any:
        source = spec.get("source")
        if source == "relative_path":
            return str(path.relative_to(self.root))
        if source == "stem":
            return path.stem
        if source == "frontmatter":
            return (frontmatter or {}).get(spec.get("key"))
        raise ValueError(f"unknown documentation collection source: {source!r}")

    def list_collection(self, collection_id: str, **filters: Any) -> list[dict[str, Any]]:
        collection = self.get_collection(collection_id)
        if collection is None:
            return []

        base = self.root / collection.path
        if not base.exists():
            return []

        needs_frontmatter = collection.format == "frontmatter" or any(
            spec.get("source") == "frontmatter"
            for spec in (collection.output or {}).values()
        ) or any(
            spec.get("source") == "frontmatter"
            for spec in (collection.filters or {}).values()
        )

        out: list[dict[str, Any]] = []
        for path in sorted(base.rglob(collection.include)):
            if not path.is_file():
                continue

            frontmatter = self._frontmatter(path) if needs_frontmatter else {}

            skip = False
            for filter_name, filter_value in filters.items():
                if filter_value is None:
                    continue
                spec = (collection.filters or {}).get(filter_name)
                if not spec:
                    continue
                actual = self._resolve_spec_value(spec, path, frontmatter)
                mode = spec.get("mode", "equals")
                if mode == "contains":
                    if filter_value not in (actual or []):
                        skip = True
                        break
                elif actual != filter_value:
                    skip = True
                    break
            if skip:
                continue

            out.append(
                {
                    name: self._resolve_spec_value(spec, path, frontmatter)
                    for name, spec in (collection.output or {}).items()
                }
            )
        return out

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

