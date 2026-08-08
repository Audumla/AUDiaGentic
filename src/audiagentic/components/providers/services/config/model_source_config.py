"""Canonical load/validate/write API for the model-sources contract.

Persisted file contract (MO01 step 9): ``{contract-version: v1, sources:
{<source-id>: <source>}}``, at two independent tiers:

- **project-local** (``.audiagentic/config/model-sources.yaml``) — the
  original, unchanged contract. Remote-account sources with project-specific
  credentials belong here.
- **user-global** (``audiagentic_home()/config/model-sources.yaml``, AS105/
  AS101) — shared local-endpoint sources (concurrency, resource-id) that
  describe machine-wide hardware, declared once rather than copied into
  every project.

``load_model_sources``/``write_model_sources`` are **project-local only,
unchanged** — every existing caller (model_source_add/update/remove/
set_enabled's read-modify-write cycle) keeps its exact current behaviour,
with zero risk of accidentally copying inherited global sources into a
project's own file. ``load_resolved_model_sources`` is the new merged view
(deep-merge of both tiers) for consumers that need the full picture, e.g.
actual provider dispatch/launch resolution -- never for round-tripping a
mutation.

The schema (``contracts/model-sources.schema.json``) is intentionally
component-only — not mirrored into ``foundation/contracts/schemas`` — because
no foundation consumer exists yet (MO01 step 11). Validation therefore reads
the schema file directly rather than going through
``foundation.contracts.schema_registry``, which only resolves schemas already
mirrored there.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import load_yaml_value, save_yaml_file
from audiagentic.foundation.paths.home import audiagentic_home

_model_sources_error = make_error_factory("VAL", "MEP", "providers")

_CONTRACT_VERSION = "v1"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "model-sources.schema.json"
_RELATIVE_CONFIG_PATH = Path(".audiagentic") / "config" / "model-sources.yaml"
# Colocated with the schema, not under config/providers/ -- that directory
# is auto-globbed as provider descriptors by
# components/providers/adapters/__init__.py, and this file is not one.
_PKG_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "model-sources-default.yaml"
)


def _schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def model_sources_path(project_root: Path) -> Path:
    """Resolve the canonical model-sources.yaml path for *project_root*."""
    return project_root / _RELATIVE_CONFIG_PATH


def validate_model_sources(payload: Any) -> list[str]:
    """Return sorted schema-validation error messages (empty list if valid)."""
    validator = Draft202012Validator(_schema())
    return sorted(error.message for error in validator.iter_errors(payload))


def _empty_document() -> dict[str, Any]:
    return {"contract-version": _CONTRACT_VERSION, "sources": {}}


def load_model_sources(project_root: Path) -> dict[str, Any]:
    """Load and validate the project's model-sources document.

    A missing file returns an empty valid v1 document. A malformed or
    schema-invalid file raises ``VAL-MEP-001`` — never silently substitutes
    an empty document for content that exists but is broken.
    """
    path = model_sources_path(project_root)
    if not path.exists():
        return _empty_document()

    payload = load_yaml_value(path, default=None)
    if payload is None:
        return _empty_document()

    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "model-sources.yaml failed schema validation",
            path=str(path),
            issues=issues,
        )
    return payload


def write_model_sources(project_root: Path, payload: dict[str, Any]) -> None:
    """Validate and atomically write the project's model-sources document."""
    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "model-sources.yaml failed schema validation",
            issues=issues,
        )
    save_yaml_file(model_sources_path(project_root), payload, atomic=True)


# ── User-global tier (AS105/AS101) — shared local-endpoint sources ────────


def user_global_model_sources_path() -> Path:
    """Resolve the user-global model-sources.yaml path.

    Machine-wide, not project-scoped: describes shared hardware (a local
    endpoint's connectivity and concurrency), not one project's intent.
    """
    return audiagentic_home() / "config" / "model-sources.yaml"


def load_user_global_model_sources() -> dict[str, Any]:
    """Load and validate the user-global model-sources document.

    A missing file returns an empty valid v1 document. Raises
    ``VAL-MEP-001`` on a malformed or schema-invalid file.
    """
    path = user_global_model_sources_path()
    if not path.exists():
        return _empty_document()

    payload = load_yaml_value(path, default=None)
    if payload is None:
        return _empty_document()

    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "user-global model-sources.yaml failed schema validation",
            path=str(path),
            issues=issues,
        )
    return payload


def write_user_global_model_sources(payload: dict[str, Any]) -> None:
    """Validate and atomically write the user-global model-sources document."""
    issues = validate_model_sources(payload)
    if issues:
        raise _model_sources_error(
            1,
            "user-global model-sources.yaml failed schema validation",
            issues=issues,
        )
    save_yaml_file(user_global_model_sources_path(), payload, atomic=True)


def load_resolved_model_sources(project_root: Path) -> dict[str, Any]:
    """Return the deep-merged view: user-global sources plus this project's
    own local sources, keyed by source-id.

    For consumers that need the full picture a source actually resolves to
    (e.g. provider dispatch/launch) — never for round-tripping a mutation.
    ``load_model_sources``/``write_model_sources`` stay project-local only
    and unchanged; mutating through the merged view would silently copy
    inherited global sources into the project's own file.
    """
    from audiagentic.foundation.config.layers import load_layered_config

    return load_layered_config(
        pkg_default_path=_PKG_DEFAULT_PATH,
        project_root=project_root,
        namespace="model-sources",
    )


__all__ = [
    "load_model_sources",
    "load_resolved_model_sources",
    "load_user_global_model_sources",
    "model_sources_path",
    "user_global_model_sources_path",
    "validate_model_sources",
    "write_model_sources",
    "write_user_global_model_sources",
]
