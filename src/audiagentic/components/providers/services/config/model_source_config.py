"""Canonical load/validate/write API for the model-sources contract.

Model sources are the ``model-sources`` section of the settings files, keyed by source id, at two
independent scopes:

- **project** (``.audiagentic/settings.yaml``): remote-account sources with project-specific
  credentials belong here.
- **user** (the user settings file): shared local-endpoint sources (concurrency, resource-id)
  that describe machine-wide hardware, declared once rather than copied into every project.

The functions keep the document shape ``{contract-version: v1, sources: {<source-id>: <source>}}``.
``load_model_sources``/``write_model_sources`` read and write the **project scope only**, so a
read-modify-write cycle can never copy an inherited user source into a project's file.
``load_resolved_model_sources`` is the merged view (user plus project) for consumers that need what
a source actually resolves to, such as provider dispatch; never for round-tripping a mutation.

The document schema (``contracts/model-sources.schema.json``) validates what these functions
accept and return; the settings section schema is the same ``source`` definition, and a test keeps
the two identical.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.config.writer import read_scope_settings, replace_section
from audiagentic.foundation.contracts.errors import make_error_factory

_model_sources_error = make_error_factory("VAL", "MEP", "providers")

_CONTRACT_VERSION = "v1"
SECTION = "model-sources"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "model-sources.schema.json"


def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_model_sources(payload: Any) -> list[str]:
    """Return sorted schema-validation error messages (empty list if valid)."""
    validator = Draft202012Validator(_schema())
    return sorted(error.message for error in validator.iter_errors(payload))


def _document(sources: Any) -> dict[str, Any]:
    return {"contract-version": _CONTRACT_VERSION, "sources": deepcopy(sources) if isinstance(sources, dict) else {}}


def _load(scope: str, project_root: Path | None, what: str) -> dict[str, Any]:
    document = _document(read_scope_settings(scope, project_root=project_root).get(SECTION))
    issues = validate_model_sources(document)
    if issues:
        raise _model_sources_error(1, f"{what} model-sources failed schema validation", issues=issues)
    return document


def _write(scope: str, project_root: Path | None, payload: dict[str, Any], what: str) -> None:
    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(1, f"{what} model-sources failed schema validation", issues=issues)
    replace_section(scope, SECTION, payload["sources"], project_root=project_root)


def load_model_sources(project_root: Path) -> dict[str, Any]:
    """The project scope's model-sources document; an absent section is an empty valid document."""
    return _load("project", project_root, "project")


def write_model_sources(project_root: Path, payload: dict[str, Any]) -> None:
    """Validate the document and make the project scope's section exactly its sources."""
    _write("project", project_root, payload, "project")


def load_user_global_model_sources() -> dict[str, Any]:
    """The user scope's model-sources document (machine-wide sources)."""
    return _load("user", None, "user")


def write_user_global_model_sources(payload: dict[str, Any]) -> None:
    _write("user", None, payload, "user")


def load_resolved_model_sources(project_root: Path) -> dict[str, Any]:
    """The merged view: user sources plus this project's own, keyed by source id."""
    return _document(resolve_settings_cached(project_root).get(SECTION))


__all__ = [
    "load_model_sources",
    "load_resolved_model_sources",
    "load_user_global_model_sources",
    "validate_model_sources",
    "write_model_sources",
    "write_user_global_model_sources",
]
