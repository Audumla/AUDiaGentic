"""Deterministic ID compaction for planning items.

Scans all planning items, assigns sequential IDs with no gaps, rewrites
cross-references, renames files, and updates counters.

Compaction only runs when current IDs are unambiguous. If malformed or duplicate
IDs exist, the run aborts before mutating files and returns a repair report.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..fs.scan import scan_items
from ..fs.write import dump_markdown
from .id_gen import _load_counters, _save_counters
from .paths import Paths
from .val_mgr import Validator


def _apply_remap(obj: object, remap: dict[str, str]) -> object:
    """Recursively replace exact-match string values using remap dict."""
    if isinstance(obj, str):
        return remap.get(obj, obj)
    if isinstance(obj, list):
        return [_apply_remap(v, remap) for v in obj]
    if isinstance(obj, dict):
        return {k: _apply_remap(v, remap) for k, v in obj.items()}
    return obj


def _build_report(
    *,
    remap: dict[str, str],
    renames: list[dict],
    counters_updated: dict[str, int] | None,
    cannot_repair: list[dict],
    already_compact: bool,
    aborted: bool,
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "already_compact": already_compact,
        "aborted": aborted,
        "remapped": len(remap),
        "renames": renames,
        "remap": remap,
        "counters_updated": counters_updated or {},
        "cannot_repair": cannot_repair,
        "repair_count": len(cannot_repair),
    }


class Compactor:
    def __init__(self, root: Path):
        self.root = root

    def run(self) -> dict:
        """Compact all planning item IDs to remove gaps.

        Steps:
        1. Scan all items and preflight malformed/duplicate IDs.
        2. Build remap: sort by current numeric ID, assign 1, 2, 3, ... per kind.
        3. Rewrite all frontmatter in-place (updates id field + all ref fields).
        4. Rename files via temp staging to avoid path collisions.
        5. Update counters.json.
        6. Run full validate; collect errors that need human/AI attention.
        """
        items = list(scan_items(self.root))
        paths = Paths(self.root)

        by_kind: dict[str, list[tuple[int, int, object]]] = defaultdict(list)
        id_to_paths: dict[str, list[str]] = defaultdict(list)
        malformed: list[dict] = []

        for index, item in enumerate(items):
            item_id = item.data.get("id", "")
            id_to_paths[item_id].append(str(item.path))
            parts = item_id.split("-", 1)
            if len(parts) != 2:
                malformed.append(
                    {
                        "id": item_id,
                        "path": str(item.path),
                        "error": "malformed ID: no dash separator",
                    }
                )
                continue
            kind, n_str = parts
            try:
                n = int(n_str)
            except ValueError:
                malformed.append(
                    {
                        "id": item_id,
                        "path": str(item.path),
                        "error": f"malformed ID: non-integer suffix {n_str!r}",
                    }
                )
                continue
            by_kind[kind].append((n, index, item))

        duplicate_ids = [
            {"id": item_id, "paths": sorted(paths_for_id)}
            for item_id, paths_for_id in sorted(id_to_paths.items())
            if item_id and len(paths_for_id) > 1
        ]

        if malformed or duplicate_ids:
            validation_errors = Validator(self.root).validate_all()
            cannot_repair = (
                [{"category": "malformed_id", **m} for m in malformed]
                + [{"category": "duplicate_id", **d} for d in duplicate_ids]
                + [{"category": "validation", "error": e} for e in validation_errors]
            )
            return _build_report(
                remap={},
                renames=[],
                counters_updated=None,
                cannot_repair=cannot_repair,
                already_compact=False,
                aborted=True,
            )

        remap: dict[str, str] = {}
        rewritten_data: dict[Path, dict] = {}

        for kind, entries in by_kind.items():
            entries.sort(key=lambda x: (x[0], x[1]))
            for new_n, (_, _, item) in enumerate(entries, start=1):
                old_id = item.data["id"]
                new_id = f"{kind}-{new_n}"
                if old_id != new_id:
                    remap[old_id] = new_id

        already_compact = not remap

        for item in items:
            rewritten_data[item.path] = _apply_remap(dict(item.data), remap)

        rename_log: list[dict] = []
        rewrite_errors: list[dict] = []
        rename_errors: list[dict] = []
        final_targets: dict[Path, list[Path]] = defaultdict(list)

        rename_ops: list[tuple[Path, Path]] = []
        for item in items:
            new_data = rewritten_data[item.path]
            new_name = paths.filename_for(item.kind, new_data["id"], new_data.get("label", ""))
            new_path = item.path.parent / new_name
            if item.path != new_path:
                rename_ops.append((item.path, new_path))
                final_targets[new_path].append(item.path)

        target_conflicts = [
            {
                "to": str(target),
                "sources": sorted(str(source) for source in sources),
                "error": "multiple files resolve to same target path",
            }
            for target, sources in sorted(final_targets.items(), key=lambda x: str(x[0]))
            if len(sources) > 1
        ]
        if target_conflicts:
            validation_errors = Validator(self.root).validate_all()
            cannot_repair = (
                [{"category": "rename_failed", **e} for e in target_conflicts]
                + [{"category": "validation", "error": e} for e in validation_errors]
            )
            return _build_report(
                remap=remap,
                renames=[],
                counters_updated=None,
                cannot_repair=cannot_repair,
                already_compact=already_compact,
                aborted=True,
            )

        for item in items:
            try:
                dump_markdown(item.path, rewritten_data[item.path], item.body)
            except Exception as exc:
                rewrite_errors.append(
                    {
                        "id": item.data.get("id", ""),
                        "path": str(item.path),
                        "error": f"write failed: {exc}",
                    }
                )

        staged_ops: list[tuple[Path, Path, Path]] = []
        for index, (old_path, new_path) in enumerate(rename_ops, start=1):
            temp_path = old_path.with_name(f".compact-{index}-{old_path.name}.tmp")
            staged_ops.append((old_path, temp_path, new_path))

        for old_path, temp_path, _ in staged_ops:
            try:
                if temp_path.exists():
                    temp_path.unlink()
                old_path.rename(temp_path)
            except Exception as exc:
                rename_errors.append(
                    {
                        "from": str(old_path),
                        "to": str(temp_path),
                        "error": str(exc),
                    }
                )

        if not rename_errors:
            for old_path, temp_path, new_path in staged_ops:
                try:
                    if new_path.exists():
                        new_path.unlink()
                    temp_path.rename(new_path)
                    rename_log.append({"from": old_path.name, "to": new_path.name})
                except Exception as exc:
                    rename_errors.append(
                        {
                            "from": str(temp_path),
                            "to": str(new_path),
                            "error": str(exc),
                        }
                    )
                    break

        for _, temp_path, _ in staged_ops:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        counters_updated: dict[str, int] = {}
        if not rewrite_errors and not rename_errors:
            counters = _load_counters(self.root)
            for kind, entries in by_kind.items():
                counters[kind] = len(entries)
            _save_counters(self.root, counters)
            counters_updated = dict(sorted(counters.items()))

        validation_errors = Validator(self.root).validate_all()
        cannot_repair = (
            [{"category": "rewrite_failed", **e} for e in rewrite_errors]
            + [{"category": "rename_failed", **e} for e in rename_errors]
            + [{"category": "validation", "error": e} for e in validation_errors]
        )

        return _build_report(
            remap=remap,
            renames=rename_log,
            counters_updated=counters_updated,
            cannot_repair=cannot_repair,
            already_compact=already_compact,
            aborted=bool(rewrite_errors or rename_errors),
        )
