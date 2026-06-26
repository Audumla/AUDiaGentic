"""Install-artifact ownership tracking for recipe prune/uninstall.

Records which files and config keys each recipe created, so teardown removes
*only* managed artifacts and leaves user customizations alone. Persisted as a
JSON sidecar under ``.audiagentic/config/runtime/toolchain/``.

Design notes (RV01): prune supports a ``dry_run`` preview and tolerates
artifacts a user has already deleted by hand — a missing file or key is reported
as ``skipped``, never an error.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config_patcher import ConfigPatcher, OwnedChange
from .managed_block import BlockChange, remove_managed_block

logger = logging.getLogger(__name__)

_SIDECAR = Path(".audiagentic") / "config" / "runtime" / "toolchain" / "artifacts.json"


@dataclass
class PruneReport:
    """Outcome of pruning one recipe's artifacts."""

    recipe: str
    dry_run: bool
    removed_files: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    removed_blocks: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class ArtifactRegistry:
    """Per-project store of recipe-owned files and config keys."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self._path = self.project_root / _SIDECAR

    # --- persistence ---------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"recipes": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("artifact registry unreadable, treating as empty: %s", self._path)
            return {"recipes": {}}
        if not isinstance(data, dict) or "recipes" not in data:
            return {"recipes": {}}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def _bucket(self, data: dict[str, Any], recipe: str) -> dict[str, Any]:
        bucket = data["recipes"].setdefault(
            recipe, {"files": [], "config_keys": [], "blocks": []}
        )
        bucket.setdefault("blocks", [])  # tolerate older sidecars
        return bucket

    # --- registration --------------------------------------------------------

    def register(
        self,
        recipe: str,
        *,
        files: list[str | Path] | None = None,
        changes: list[OwnedChange] | None = None,
        blocks: list[BlockChange] | None = None,
    ) -> list[str]:
        """Record artifacts a recipe owns. Returns collision warnings (if any).

        A collision is an artifact already owned by a *different* recipe; it is
        recorded anyway but surfaced so callers can flag overlapping ownership.
        """
        data = self._load()
        bucket = self._bucket(data, recipe)
        collisions: list[str] = []

        for f in files or []:
            ident = Path(f).as_posix()
            other = self._owner_of(data, "files", ident, exclude=recipe)
            if other:
                collisions.append(f"file {ident} already owned by {other}")
            if ident not in bucket["files"]:
                bucket["files"].append(ident)

        for change in changes or []:
            entry = {
                "artifact_id": change.artifact_id,
                "path": change.path,
                "key_path": list(change.key_path),
            }
            other = self._owner_of(data, "config_keys", change.artifact_id, exclude=recipe)
            if other:
                collisions.append(f"config key {change.artifact_id} already owned by {other}")
            if not any(e["artifact_id"] == change.artifact_id for e in bucket["config_keys"]):
                bucket["config_keys"].append(entry)

        for block in blocks or []:
            entry = {
                "artifact_id": block.artifact_id,
                "path": block.path,
                "block_id": block.block_id,
            }
            other = self._owner_of(data, "blocks", block.artifact_id, exclude=recipe)
            if other:
                collisions.append(f"block {block.artifact_id} already owned by {other}")
            if not any(e["artifact_id"] == block.artifact_id for e in bucket["blocks"]):
                bucket["blocks"].append(entry)

        self._save(data)
        return collisions

    @staticmethod
    def _owner_of(
        data: dict[str, Any], category: str, ident: str, *, exclude: str
    ) -> str | None:
        for name, bucket in data["recipes"].items():
            if name == exclude:
                continue
            for item in bucket.get(category, []):
                value = item if isinstance(item, str) else item.get("artifact_id")
                if value == ident:
                    return name
        return None

    # --- queries -------------------------------------------------------------

    def owned(self, recipe: str) -> dict[str, Any]:
        """Return the artifacts owned by ``recipe`` (empty bucket if none)."""
        data = self._load()
        return data["recipes"].get(
            recipe, {"files": [], "config_keys": [], "blocks": []}
        )

    def recipes(self) -> list[str]:
        return sorted(self._load()["recipes"].keys())

    # --- prune ---------------------------------------------------------------

    def prune(self, recipe: str, *, dry_run: bool = False) -> PruneReport:
        """Remove only ``recipe``-owned artifacts. Missing ones are skipped.

        On a non-dry run, the recipe's registry entry is cleared afterward.
        """
        data = self._load()
        bucket = data["recipes"].get(recipe)
        report = PruneReport(recipe=recipe, dry_run=dry_run)
        if not bucket:
            return report

        for ident in bucket.get("files", []):
            target = self.project_root / ident if not Path(ident).is_absolute() else Path(ident)
            if not target.exists():
                report.skipped.append(f"file absent: {ident}")
                continue
            if dry_run:
                report.removed_files.append(ident)
                continue
            try:
                target.unlink()
                report.removed_files.append(ident)
            except OSError as exc:
                report.errors.append(f"file {ident}: {exc}")

        for entry in bucket.get("config_keys", []):
            ident = entry["artifact_id"]
            cfg_path = Path(entry["path"])
            key_path = tuple(entry["key_path"])
            if not cfg_path.is_absolute():
                cfg_path = self.project_root / cfg_path
            if not cfg_path.exists():
                report.skipped.append(f"config absent: {ident}")
                continue
            if dry_run:
                report.removed_keys.append(ident)
                continue
            try:
                change = ConfigPatcher(cfg_path).remove_key(key_path)
                if change.existed:
                    report.removed_keys.append(ident)
                else:
                    report.skipped.append(f"key absent: {ident}")
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"config key {ident}: {exc}")

        for entry in bucket.get("blocks", []):
            ident = entry["artifact_id"]
            blk_path = Path(entry["path"])
            if not blk_path.is_absolute():
                blk_path = self.project_root / blk_path
            if not blk_path.exists():
                report.skipped.append(f"block file absent: {ident}")
                continue
            if dry_run:
                report.removed_blocks.append(ident)
                continue
            try:
                change = remove_managed_block(blk_path, entry["block_id"])
                if change.existed:
                    report.removed_blocks.append(ident)
                else:
                    report.skipped.append(f"block absent: {ident}")
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"block {ident}: {exc}")

        if not dry_run and report.ok:
            del data["recipes"][recipe]
            self._save(data)
        return report


__all__ = ["ArtifactRegistry", "PruneReport"]
