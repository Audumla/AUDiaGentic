from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.paths import SRC_ROOT

from .base import SurfaceContribution

_CONFIG_ROOT = SRC_ROOT / "audiagentic" / "config"


def _as_strings(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _contributions_from_data(data: dict[str, Any], component_id: str) -> list[SurfaceContribution]:
    contributions: list[SurfaceContribution] = []
    for raw in data.get("surface-contributions") or []:
        if not isinstance(raw, dict):
            continue
        content = raw.get("content") or {}
        body = content.get("body") if isinstance(content, dict) else raw.get("body")
        if not isinstance(body, str):
            continue
        contribution_id = raw.get("id")
        kind = raw.get("kind")
        title = raw.get("title") or raw.get("summary")
        if not all(isinstance(item, str) and item for item in (contribution_id, kind, title)):
            continue
        contributions.append(
            SurfaceContribution(
                contribution_id=contribution_id,
                owner_component=raw.get("owner") if isinstance(raw.get("owner"), str) else component_id,
                kind=kind,
                title=title,
                body=body,
                preferred_targets=_as_strings(raw.get("preferred-targets")),
            )
        )
    return contributions


def load_surface_contributions(config_root: Path | None = None) -> list[SurfaceContribution]:
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import all_descriptors

    register_all_components()
    root = (config_root or _CONFIG_ROOT).resolve()
    contributions: list[SurfaceContribution] = []
    for descriptor in sorted(all_descriptors().values(), key=lambda d: d.component_id):
        if not descriptor.config_path:
            continue
        config_file = root / descriptor.config_path
        if not config_file.exists():
            continue
        data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        contributions.extend(_contributions_from_data(data, descriptor.component_id))
    return contributions
