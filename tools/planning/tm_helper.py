#!/usr/bin/env python3
"""Thin planning helper with documentation-surface support.

Support docs are surfaced here as structured sidecar docs rather than core
planning kinds in this phase.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
import yaml

def _find_project_root() -> Path:
    """Find AUDiaGentic project root containing .audiagentic/planning/.

    Search strategy:
    1. Check current working directory and all parents for .audiagentic/planning
    2. Check module directory parents as fallback
    3. Raise error if not found

    Returns:
        Path to project root

    Raises:
        RuntimeError: If project root cannot be determined
    """
    # Strategy 1: Search from cwd upward
    for p in [Path.cwd(), *Path.cwd().parents]:
        if (p / ".audiagentic" / "planning").exists():
            return p

    # Strategy 2: Search from module location upward
    module_dir = Path(__file__).resolve().parent
    for p in [module_dir, *module_dir.parents]:
        if (p / ".audiagentic" / "planning").exists():
            return p

    # Strategy 3: Last resort - check typical locations
    # This handles the case where we're in tools/planning/ relative to root
    likely_root = module_dir.parent.parent.parent
    if (likely_root / ".audiagentic" / "planning").exists():
        return likely_root

    raise RuntimeError(
        f"Could not find project root with .audiagentic/planning/. "
        f"Searched from cwd={Path.cwd()} and module={module_dir}"
    )


_ROOT = _find_project_root()
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.docs_mgr import DocumentationManager
from audiagentic.planning.app.refs_mgr import ReferencesManager
from audiagentic.planning.app.support_mgr import SupportingDocsManager
from audiagentic.planning.app.section_registry import split_section_path

_api = PlanningAPI(_ROOT)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _docs_manager() -> DocumentationManager:
    return DocumentationManager(
        _ROOT, _load_yaml(_ROOT / ".audiagentic/planning/config/documentation.yaml")
    )


def new_request(label: str, summary: str) -> dict[str, Any]:
    item = _api.new("request", label=label, summary=summary)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_spec(
    label: str, summary: str, request_refs: list[str] | None = None
) -> dict[str, Any]:
    item = _api.new("spec", label=label, summary=summary, request_refs=request_refs)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def _validate_reference(ref_id: str, ref_type: str) -> None:
    """Validate that a referenced planning item exists.

    Args:
        ref_id: Planning item ID to validate
        ref_type: Type of reference (e.g., 'spec', 'plan') for error message

    Raises:
        ValueError: If reference does not exist
    """
    try:
        _api._find(ref_id)
    except KeyError:
        raise ValueError(f"{ref_type} '{ref_id}' does not exist")


def new_plan(label: str, summary: str, spec: str | None = None) -> dict[str, Any]:
    if spec:
        _validate_reference(spec, "spec")
    item = _api.new("plan", label=label, summary=summary, spec=spec)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    # Validate spec exists (required for task)
    _validate_reference(spec, "spec")

    # Validate optional references
    if parent:
        _validate_reference(parent, "parent")

    item = _api.new(
        "task",
        label=label,
        summary=summary,
        spec=spec,
        domain=domain,
        target=target,
        parent=parent,
        workflow=workflow,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_wp(
    label: str, summary: str, plan: str, domain: str = "core", workflow: str | None = None
) -> dict[str, Any]:
    # Validate plan exists (required for work package)
    _validate_reference(plan, "plan")

    item = _api.new(
        "wp", label=label, summary=summary, plan=plan, domain=domain, workflow=workflow
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_standard(label: str, summary: str) -> dict[str, Any]:
    item = _api.new("standard", label=label, summary=summary)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def state(id_: str, new_state: str) -> dict[str, Any]:
    item = _api.state(id_, new_state)
    return {"id": item.data["id"], "state": item.data["state"]}


def move(id_: str, domain: str) -> dict[str, Any]:
    item = _api.move(id_, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def update(
    id_: str,
    label: str | None = None,
    summary: str | None = None,
    append: str | None = None,
) -> dict[str, Any]:
    item = _api.update(id_, label=label, summary=summary, body_append=append)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def get_content(id_: str) -> str:
    return _api.get_content(id_)


def update_content(
    id_: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    item = _api.update_content(id_, content, mode, section, position)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def create_with_content(
    kind: str,
    label: str,
    summary: str,
    content: str,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    item = _api.create_with_content(
        kind, label, summary, content, domain, spec, plan, parent, target, workflow, request_refs
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    item = _api.relink(src, field, dst, seq, display)
    return {"id": item.data["id"], "field": field}


def package(plan: str, tasks: list[str], label: str, summary: str, domain: str = "core") -> dict[str, Any]:
    item = _api.package(plan, tasks, label, summary, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def validate() -> list[str]:
    return _api.validate()


def index() -> None:
    _api.index()


def reconcile() -> dict[str, Any]:
    return _api.reconcile()


def show(id_: str) -> dict[str, Any]:
    return _api.extracts.show(id_)


def extract(id_: str, with_related: bool = False, with_resources: bool = False) -> dict[str, Any]:
    return _api.extracts.extract(id_, with_related, with_resources)


def list_kind(kind: str | None = None) -> list[dict[str, Any]]:
    items = _api._scan()
    if kind:
        items = [i for i in items if i.kind == kind]
    return [
        {"id": i.data["id"], "kind": i.kind, "label": i.data["label"], "state": i.data["state"]}
        for i in items
    ]


def next_items(kind: str = "task", state: str = "ready", domain: str | None = None) -> list[dict[str, Any]]:
    return _api.next_items(kind, state, domain)


def next_tasks(state: str = "ready", domain: str | None = None) -> list[dict[str, Any]]:
    return next_items("task", state, domain)


def claim(kind: str, id_: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    return _api.claim(kind, id_, holder, ttl)


def unclaim(id_: str) -> bool:
    return _api.unclaim(id_)


def claims(kind: str | None = None) -> list[dict[str, Any]]:
    return _api.claims(kind)


def standards(id_: str) -> list[str]:
    return _api.standards(id_)


def events(tail: int = 20) -> list[dict[str, Any]]:
    import json

    p = _ROOT / ".audiagentic/planning/events/events.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()[-tail:]
    return [json.loads(x) for x in lines if x.strip()]


def status() -> dict[str, Any]:
    items = _api._scan()
    out: dict[str, dict[str, int]] = {}
    for i in items:
        out.setdefault(i.kind, {})
        out[i.kind].setdefault(i.data["state"], 0)
        out[i.kind][i.data["state"]] += 1
    return out


def list_doc_surfaces() -> list[dict[str, Any]]:
    return [s.__dict__ for s in _docs_manager().list_surfaces()]


def get_doc_surface(surface_id: str) -> dict[str, Any] | None:
    """Get a documentation surface by ID.

    Args:
        surface_id: The surface ID to retrieve

    Returns:
        Surface data dict, or None if not found
    """
    surface = _docs_manager().get_surface(surface_id)
    return None if surface is None else surface.__dict__


def list_reference_docs() -> list[dict[str, str]]:
    """List all reference documentation files.

    Returns:
        List of {path, label} dicts for each reference doc
    """
    return ReferencesManager(_ROOT).list_reference_docs()


def list_request_profiles() -> list[dict[str, Any]]:
    """List all request profile templates.

    Returns:
        List of profile configs (feature, issue, etc.)
    """
    cfg = _load_yaml(_ROOT / ".audiagentic/planning/config/request-profiles.yaml")
    profiles = cfg.get("request_profiles", {})
    out = []
    for name, data in profiles.items():
        row = {"id": name}
        if isinstance(data, dict):
            row.update(data)
        out.append(row)
    return out


def get_request_profile(profile_id: str) -> dict[str, Any] | None:
    """Get a request profile by ID.

    Args:
        profile_id: The profile ID to retrieve (e.g., 'feature', 'issue')

    Returns:
        Profile data dict with id and config fields, or None if not found
    """
    cfg = _load_yaml(_ROOT / ".audiagentic/planning/config/request-profiles.yaml")
    data = cfg.get("request_profiles", {}).get(profile_id)
    if data is None:
        return None
    row = {"id": profile_id}
    if isinstance(data, dict):
        row.update(data)
    return row


def list_support_docs(supports_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    return SupportingDocsManager(_ROOT).list_support_docs(supports_id, role)


def _find_section(lines: list[str], target_name: str, level: int = 1) -> tuple[int | None, int | None]:
    """Find a section by name and return (start, end) line indices.

    Args:
        lines: List of markdown lines
        target_name: Section name to find (spaces/underscores normalized)
        level: Heading level to match (1 for #, 2 for ##, etc.)

    Returns:
        (start, end) tuple where start is first line after heading and end is line of next heading.
        Returns (None, None) if section not found.
    """
    target = target_name.replace("_", " ").strip().lower()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.startswith("#" * level) and not line.startswith("#" * (level + 1)):
            heading = line.lstrip("#").strip().lower()
            if heading == target:
                start = i + 1
                continue
            if start is not None and end is None:
                end = i
                break
    if start is not None and end is None:
        end = len(lines)
    return (start, end) if start is not None else (None, None)


def _replace_section_body(text: str, section: str, content: str, append: bool = False) -> str:
    lines = text.splitlines()
    start, end = _find_section(lines, section, level=1)

    if start is None:
        # Section doesn't exist; create it
        heading = section.replace("_", " ").title()
        return text.rstrip() + f"\n\n# {heading}\n\n" + content.strip() + "\n"

    old = "\n".join(lines[start:end]).strip()
    new_body = (old + "\n\n" + content.strip()).strip() if append and old else content.strip()
    new_lines = lines[:start] + ([new_body] if new_body else []) + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"


def get_section(id_: str, section: str) -> dict[str, Any]:
    text = get_content(id_)
    lines = text.splitlines()
    start, end = _find_section(lines, section, level=1)

    if start is None:
        return {"id": id_, "section": section, "content": "", "found": False}

    content = "\n".join(lines[start:end]).strip()
    return {"id": id_, "section": section, "content": content, "found": True}


def set_section(id_: str, section: str, content: str) -> dict[str, Any]:
    return update_content(id_, _replace_section_body(get_content(id_), section, content, append=False), mode="replace")


def append_section(id_: str, section: str, content: str) -> dict[str, Any]:
    return update_content(id_, _replace_section_body(get_content(id_), section, content, append=True), mode="replace")


def get_subsection(id_: str, section_path: str) -> dict[str, Any]:
    """Get nested subsection content using dot or slash notation.

    Supports arbitrary heading levels (doesn't assume sequential ##, ###, etc.).

    Args:
        id_: Planning item ID
        section_path: Subsection path ("section.subsection" or "section/subsection")

    Returns:
        Dict with id, section_path, content, and found flag
    """
    parts = split_section_path(section_path)
    if not parts:
        return {"id": id_, "section_path": section_path, "content": "", "found": False}

    # Start with the top-level section
    current = get_section(id_, parts[0])
    if not current.get("found"):
        return {"id": id_, "section_path": section_path, "content": "", "found": False}

    text = current.get("content", "")
    if len(parts) == 1:
        return {"id": id_, "section_path": section_path, "content": text, "found": True}

    # Traverse nested subsections without assuming specific heading levels
    lines = text.splitlines()
    for target_raw in parts[1:]:
        # Try each heading level starting from 2 (##) up to 6 (#####)
        # This handles non-sequential heading structures
        found = False
        for level in range(2, 7):
            start, end = _find_section(lines, target_raw, level=level)
            if start is not None:
                text = "\n".join(lines[start:end]).strip()
                lines = text.splitlines()
                found = True
                break

        if not found:
            return {"id": id_, "section_path": section_path, "content": "", "found": False}

    return {"id": id_, "section_path": section_path, "content": text, "found": True}


def _validate_profile_pack(profile_pack: str) -> None:
    """Validate that a profile pack exists and is loadable.

    Raises:
        ValueError: If profile pack doesn't exist or is invalid
    """
    path = _ROOT / f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    if not path.exists():
        raise ValueError(
            f"Profile pack '{profile_pack}' not found at {path}. "
            f"Check .audiagentic/planning/config/profile-packs/ for available packs."
        )
    cfg = _load_yaml(path)
    if "profile_pack" not in cfg:
        raise ValueError(
            f"Profile pack '{profile_pack}' is missing 'profile_pack' key. Check YAML structure."
        )


def get_doc_sync_requirements(kind: str, profile_pack: str = "standard") -> dict[str, Any]:
    _validate_profile_pack(profile_pack)
    cfg = _load_yaml(_ROOT / f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml")
    pp = cfg.get("profile_pack", {})
    return {
        "profile_pack": profile_pack,
        "kind": kind,
        "required_updates": _docs_manager().pending_updates_for_kind(kind, pp),
        "all_required_updates": _docs_manager().profile_pack_required_updates(pp),
    }


def pending_doc_updates(kind: str, profile_pack: str = "standard") -> list[str]:
    _validate_profile_pack(profile_pack)
    cfg = _load_yaml(_ROOT / f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml")
    return _docs_manager().pending_updates_for_kind(kind, cfg.get("profile_pack", {}))


def verify_structure() -> dict[str, Any]:
    """Verify the planning module structure is sound.

    Performs a basic health check on:
    - Required directories (created on init)
    - Required config files (core planning configs)
    - Optional extension configs (request profiles, documentation surfaces)
    - API accessibility and document scanning

    Returns:
        {
            "root": str,
            "healthy": bool,
            "checks": {check_name: {"ok": bool, "required": bool, "message": str}},
            "summary": str
        }
    """
    checks = {}

    # Check root directory
    checks["root_exists"] = {
        "ok": _ROOT.exists(),
        "required": True,
        "message": f"Root directory exists: {_ROOT}",
    }

    # Check required directories (created on baseline_sync)
    required_dirs = [
        ".audiagentic/planning",
        ".audiagentic/planning/config",
        ".audiagentic/planning/ids",
        ".audiagentic/planning/indexes",
        ".audiagentic/planning/events",
    ]
    for dir_rel in required_dirs:
        dir_path = _ROOT / dir_rel
        checks[f"dir_{dir_rel.replace('/', '_')}"] = {
            "ok": dir_path.is_dir(),
            "required": True,
            "message": f"Directory exists: {dir_rel}",
        }

    # Check required config files (core planning)
    required_configs = [
        ".audiagentic/planning/config/planning.yaml",
        ".audiagentic/planning/config/workflows.yaml",
        ".audiagentic/planning/config/automations.yaml",
        ".audiagentic/planning/config/hooks.yaml",
    ]
    for cfg_rel in required_configs:
        cfg_path = _ROOT / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": True,
            "message": f"Config file exists: {cfg_rel}",
        }

    # Check optional extension configs (Phase 2 doc surfaces)
    optional_configs = [
        ".audiagentic/planning/config/request-profiles.yaml",
        ".audiagentic/planning/config/documentation.yaml",
    ]
    for cfg_rel in optional_configs:
        cfg_path = _ROOT / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": False,
            "message": f"Config file exists (optional): {cfg_rel}",
        }

    # Check API initialization (required for planning functionality)
    try:
        _api.validate()
        checks["api_accessible"] = {
            "ok": True,
            "required": True,
            "message": "PlanningAPI is accessible and docs are valid",
        }
    except Exception as e:
        checks["api_accessible"] = {
            "ok": False,
            "required": True,
            "message": f"PlanningAPI error: {e}",
        }

    # Count existing items (informational only)
    try:
        items = _api._scan()
        checks["items_scannable"] = {
            "ok": True,
            "required": False,
            "message": f"Found {len(items)} planning items",
        }
    except Exception as e:
        checks["items_scannable"] = {
            "ok": False,
            "required": False,
            "message": f"Scan error: {e}",
        }

    # Overall health: only required checks determine healthiness
    required_failures = [k for k, v in checks.items() if v.get("required", False) and not v.get("ok", False)]
    optional_failures = [k for k, v in checks.items() if not v.get("required", False) and not v.get("ok", False)]
    healthy = len(required_failures) == 0

    if required_failures:
        summary = f"Structure check FAILED: {len(required_failures)} required check(s) failed - {', '.join(required_failures)}."
        if optional_failures:
            summary += f" ({len(optional_failures)} optional checks also missing)"
    elif optional_failures:
        summary = f"Structure check OK: {len(optional_failures)} optional extension(s) not installed - {', '.join(optional_failures)}"
    else:
        summary = "Structure check PASSED: planning module is healthy and fully equipped"

    return {
        "root": str(_ROOT),
        "healthy": healthy,
        "checks": checks,
        "summary": summary,
    }
