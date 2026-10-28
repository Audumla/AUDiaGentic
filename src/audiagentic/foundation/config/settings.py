"""Layered settings: the canonical configuration resolver.

Contract: docs/design/configuration-model.md (plan config-setup, CFG03).
Foundation owns the mechanics only: scopes, discovery, strict loading,
RFC 7396 merge with provenance, and validation. The schema is the envelope in
the canonical schema registry (``settings``) composed with the sections that
components declare in ``config/components/<component>/settings/<section>.schema.json``.

Phase 1 scopes, lowest precedence first: vendor (packaged
``config/provisioning/foundation/settings.yaml``), user (platform config dir),
project (current checkout's tracked ``.audiagentic/settings.yaml``), explicit
(``--config`` / ``AUDIAGENTIC_CONFIG``), then CLI overrides. Resolution never
creates files or directories. New configuration consumers use
``resolve_settings``; ``layers.load_layered_config`` must not gain callers.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.paths.home import user_config_dir
from audiagentic.foundation.paths.names import get_component_config_dirs, get_package_config_dir
from audiagentic.foundation.paths.project import discover_checkout_root

from .merge import Origin, merge_patch, without_nulls
from .strict_yaml import LoadedDocument, Position, json_pointer, load_settings_file, settings_error

SETTINGS_FILE = "settings.yaml"
CONFIG_ENV = "AUDIAGENTIC_CONFIG"
PROJECT_ENV = "AUDIAGENTIC_PROJECT"


@dataclass(frozen=True)
class ScopeSource:
    scope: str
    path: Path | None
    required: bool

    @property
    def present(self) -> bool:
        return self.path is not None and self.path.is_file()


@dataclass(frozen=True)
class SettingsIssue:
    file: str | None
    line: int | None
    column: int | None
    pointer: str
    message: str

    def describe(self) -> str:
        where = self.file or "effective settings"
        if self.line is not None:
            where += f":{self.line}:{self.column}"
        return f"{where}: {self.pointer or '/'}: {self.message}"


@dataclass(frozen=True)
class ResolvedSettings:
    values: dict[str, Any]
    origins: dict[str, Origin]
    sources: tuple[ScopeSource, ...]
    project_root: Path | None
    issues: tuple[SettingsIssue, ...] = field(default=())

    def get(self, key: str, default: Any = None) -> Any:
        """Look up a dotted key such as ``agents.default``."""
        value: Any = self.values
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def origin(self, key: str) -> Origin | None:
        return self.origins.get(json_pointer(tuple(key.split("."))))


def vendor_settings_path() -> Path:
    return get_package_config_dir() / "provisioning" / "foundation" / SETTINGS_FILE


def settings_schema() -> dict[str, Any]:
    """The registry envelope composed with every component-declared section."""
    schema = read_schema("settings")
    properties = dict(schema.get("properties", {}))
    owners: dict[str, Path] = {}
    for base in get_component_config_dirs():
        for path in sorted(base.glob("*/settings/*.schema.json")):
            section = path.name[: -len(".schema.json")]
            if section in properties:
                raise settings_error(
                    7, "Settings section is declared more than once", section=section,
                    files=[str(owners.get(section, "settings envelope")), str(path)],
                )
            owners[section] = path
            properties[section] = json.loads(path.read_text(encoding="utf-8"))
    return {**schema, "properties": properties}


def discover_project_root(
    project: Path | str | None = None,
    *,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """``--project``, else ``AUDIAGENTIC_PROJECT``, else the current git checkout."""
    environ = os.environ if environ is None else environ
    explicit = project if project is not None else environ.get(PROJECT_ENV) or None
    if explicit is not None:
        root = Path(explicit).expanduser()
        if not root.is_dir():
            raise settings_error(5, "Project directory does not exist", project=str(root))
        return root.resolve()
    return discover_checkout_root(cwd)


def scope_sources(
    *,
    project_root: Path | None,
    config_file: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[ScopeSource, ...]:
    environ = os.environ if environ is None else environ
    sources = [
        ScopeSource("vendor", vendor_settings_path(), required=True),
        ScopeSource("user", user_config_dir() / SETTINGS_FILE, required=False),
        ScopeSource(
            "project", project_root / ".audiagentic" / SETTINGS_FILE if project_root else None, required=False,
        ),
    ]
    explicit = config_file if config_file is not None else environ.get(CONFIG_ENV) or None
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise settings_error(6, "Explicit settings file does not exist", file=str(path))
        sources.append(ScopeSource("explicit", path.resolve(), required=True))
    return tuple(sources)


def _issues(
    validator: Draft202012Validator, instance: Any, file: str | None, positions: Mapping[str, Position],
) -> list[SettingsIssue]:
    found = []
    for error in validator.iter_errors(instance):
        parts = tuple(error.absolute_path)
        position = None
        lookup = parts
        while position is None:
            position = positions.get(json_pointer(lookup))
            if not lookup:
                break
            lookup = lookup[:-1]
        found.append(SettingsIssue(
            file, position.line if position else None, position.column if position else None,
            json_pointer(parts), error.message,
        ))
    return sorted(found, key=lambda issue: (issue.line or 0, issue.column or 0, issue.pointer))


def resolve_settings(
    *,
    project: Path | str | None = None,
    config_file: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
    collect: bool = False,
) -> ResolvedSettings:
    """Load vendor, user, project and explicit scopes, then CLI ``overrides``.

    Each file is validated on its own (deletion markers removed) so errors
    point at the file that introduced them; the merged result is validated
    again as the effective configuration. By default the first invalid file
    raises ``CFG-SET-004``; with ``collect=True`` schema issues are returned
    for ``config validate``. Unreadable or syntactically invalid YAML always
    raises.
    """
    validator = Draft202012Validator(settings_schema())
    project_root = discover_project_root(project, cwd=cwd, environ=environ)
    sources = scope_sources(project_root=project_root, config_file=config_file, environ=environ)
    values: dict[str, Any] = {}
    origins: dict[str, Origin] = {}
    issues: list[SettingsIssue] = []
    for source in sources:
        if not source.present:
            if source.required:
                raise settings_error(1, "Required settings file is missing", scope=source.scope, file=str(source.path))
            continue
        document = load_settings_file(source.path)
        file_issues = _issues(validator, without_nulls(document.data), str(source.path), document.positions)
        if file_issues and not collect:
            _raise(file_issues)
        issues.extend(file_issues)
        values = merge_patch(values, document.data, origins, _origin_of(source.scope, document))
    if overrides:
        values = merge_patch(values, dict(overrides), origins, lambda pointer: Origin("cli"))
    if not issues:
        for issue in _issues(validator, values, None, {}):
            origin = origins.get(issue.pointer)
            if origin is not None:
                issue = SettingsIssue(origin.file, origin.line, origin.column, issue.pointer, issue.message)
            issues.append(issue)
        if issues and not collect:
            _raise(issues)
    return ResolvedSettings(values, origins, sources, project_root, tuple(issues))


def _origin_of(scope: str, document: LoadedDocument):
    def origin(pointer: str) -> Origin:
        position = document.positions.get(pointer)
        return Origin(scope, str(document.path), position.line if position else None,
                      position.column if position else None)
    return origin


def _raise(issues: list[SettingsIssue]) -> None:
    first = issues[0]
    raise settings_error(
        4, f"Invalid settings: {first.message}", file=first.file, line=first.line, column=first.column,
        pointer=first.pointer or "/", issues=len(issues),
    )
