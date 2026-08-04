"""CRUD and projection helpers for project-owned agent surfaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _validate_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise AudiaGenticError(
            code="VAL-PROJSURF-001", kind="project", message="invalid surface id",
            details={"id": value, "pattern": _ID_RE.pattern},
        )
    return value


def _instructions_dir(root: Path) -> Path:
    return root / ".audiagentic" / "config" / "project" / "instructions"


def _instruction_path(root: Path, item_id: str) -> Path:
    return _instructions_dir(root) / f"{_validate_id(item_id)}.yaml"


def _skills_dir(root: Path) -> Path:
    return root / ".audiagentic" / "skills"


def _skill_path(root: Path, item_id: str) -> Path:
    return _skills_dir(root) / f"project-{_validate_id(item_id)}" / "skill.md"


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AudiaGenticError(
            code="IO-PROJSURF-001", kind="project", message="project instruction is unreadable",
            details={"path": str(path)},
        ) from exc
    if not isinstance(data, dict):
        raise AudiaGenticError(
            code="VAL-PROJSURF-002", kind="project", message="project instruction must be a mapping",
            details={"path": str(path)},
        )
    return data


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AudiaGenticError(
            code="VAL-PROJSURF-003", kind="project", message=f"{field} must be non-empty text",
            details={"field": field},
        )
    return value


def _reconcile(root: Path) -> None:
    from audiagentic.components.providers.skill_surfaces import regenerate_skill_surfaces
    from audiagentic.components.providers.surfaces.manager import apply_provider_surfaces

    apply_provider_surfaces(root)
    regenerate_skill_surfaces(root)


def list_project_instructions(root: Path) -> list[dict[str, Any]]:
    directory = _instructions_dir(root)
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.yaml")):
        data = _read_yaml(path)
        result.append({"id": path.stem, **data})
    return result


def get_project_instruction(root: Path, item_id: str) -> dict[str, Any]:
    path = _instruction_path(root, item_id)
    if not path.exists():
        raise AudiaGenticError(code="RES-PROJSURF-001", kind="project", message="project instruction not found", details={"id": item_id})
    return {"id": item_id, **_read_yaml(path)}


def create_project_instruction(root: Path, item_id: str, title: str, body: str, preferred_targets: list[str] | None = None) -> dict[str, Any]:
    path = _instruction_path(root, item_id)
    if path.exists():
        raise AudiaGenticError(code="CON-PROJSURF-001", kind="project", message="project instruction already exists", details={"id": item_id})
    _require_text(title, "title")
    _require_text(body, "body")
    data = {"id": item_id, "title": title, "preferred-targets": preferred_targets or ["instruction"], "content": {"body": body}}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    _reconcile(root)
    return {"id": item_id, "title": title, "preferred-targets": data["preferred-targets"], "content": {"body": body}}


def update_project_instruction(root: Path, item_id: str, title: str | None = None, body: str | None = None, preferred_targets: list[str] | None = None) -> dict[str, Any]:
    current = get_project_instruction(root, item_id)
    if title is not None:
        current["title"] = _require_text(title, "title")
    if body is not None:
        current.setdefault("content", {})["body"] = _require_text(body, "body")
    if preferred_targets is not None:
        current["preferred-targets"] = preferred_targets
    atomic_write_text(_instruction_path(root, item_id), yaml.safe_dump({k: v for k, v in current.items() if k != "id"}, sort_keys=False, allow_unicode=True))
    _reconcile(root)
    return current


def delete_project_instruction(root: Path, item_id: str) -> dict[str, Any]:
    path = _instruction_path(root, item_id)
    if not path.exists():
        raise AudiaGenticError(code="RES-PROJSURF-001", kind="project", message="project instruction not found", details={"id": item_id})
    path.unlink()
    _reconcile(root)
    return {"id": item_id, "deleted": True}


def list_project_skills(root: Path) -> list[dict[str, Any]]:
    directory = _skills_dir(root)
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("project-*/skill.md")):
        result.append({"id": path.parent.name.removeprefix("project-"), "content": path.read_text(encoding="utf-8")})
    return result


def get_project_skill(root: Path, item_id: str) -> dict[str, Any]:
    path = _skill_path(root, item_id)
    if not path.exists():
        raise AudiaGenticError(code="RES-PROJSURF-002", kind="project", message="project skill not found", details={"id": item_id})
    return {"id": item_id, "content": path.read_text(encoding="utf-8")}


def _validate_skill(content: str) -> str:
    content = _require_text(content, "content")
    if not content.startswith("---\n") or "\n---" not in content:
        raise AudiaGenticError(code="VAL-PROJSURF-004", kind="project", message="skill content must contain YAML frontmatter", details={})
    return content


def create_project_skill(root: Path, item_id: str, content: str) -> dict[str, Any]:
    path = _skill_path(root, item_id)
    if path.exists():
        raise AudiaGenticError(code="CON-PROJSURF-002", kind="project", message="project skill already exists", details={"id": item_id})
    content = _validate_skill(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, content if content.endswith("\n") else content + "\n")
    _reconcile(root)
    return {"id": item_id, "content": content}


def update_project_skill(root: Path, item_id: str, content: str) -> dict[str, Any]:
    get_project_skill(root, item_id)
    content = _validate_skill(content)
    atomic_write_text(_skill_path(root, item_id), content if content.endswith("\n") else content + "\n")
    _reconcile(root)
    return {"id": item_id, "content": content}


def delete_project_skill(root: Path, item_id: str) -> dict[str, Any]:
    path = _skill_path(root, item_id)
    if not path.exists():
        raise AudiaGenticError(code="RES-PROJSURF-002", kind="project", message="project skill not found", details={"id": item_id})
    path.unlink()
    if not any(path.parent.iterdir()):
        path.parent.rmdir()
    _reconcile(root)
    return {"id": item_id, "deleted": True}
