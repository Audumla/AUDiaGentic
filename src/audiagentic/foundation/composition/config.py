"""Composition configuration: roots and bindings, and nothing else.

Hosted on the existing three-tier `load_layered_config` precedence API — this
adds no loader of its own. The schema is deliberately two keys wide:

    composition:
      roots:
        - runtime.application-host
      bindings:
        runtime.application-host: runtime.default-host

Configuration selects *stable identifiers*. A Python path, dotted module
reference or `module:attr` target in either key is rejected here, in validation
code rather than only in a test, because that rule is what keeps composition
config from becoming a second way to execute code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.composition.contracts import (
    ImplementationId,
    ServiceId,
    composition_error,
)

CONFIG_NAMESPACE = "composition"

# An identifier is dotted-lowercase with hyphens: "runtime.application-host".
# Deliberately narrow — it must not be able to name a Python attribute path.
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")

# Rejected outright: anything that looks like a code reference rather than a
# name. `.py` and `:` are unambiguous; a segment in PascalCase or containing an
# underscore is how a Python module/attribute path would show up.
_CODE_REFERENCE_MARKERS = (".py", ":", "/", "\\", "_")


def _reject_code_reference(value: str, *, where: str) -> None:
    for marker in _CODE_REFERENCE_MARKERS:
        if marker in value:
            raise composition_error(
                2,
                f"Composition config must name identifiers, not Python paths: {value!r} "
                f"in {where}. Bindings select an implementation-id; code supplies the factory.",
                value=value,
                location=where,
                marker=marker,
            )
    if any(segment[:1].isupper() for segment in value.split(".")):
        raise composition_error(
            2,
            f"Composition config must name identifiers, not Python paths: {value!r} "
            f"in {where}. Identifiers are lowercase; a capitalised segment reads as a class.",
            value=value,
            location=where,
        )
    if not _ID_PATTERN.match(value):
        raise composition_error(
            2,
            f"Malformed composition identifier {value!r} in {where}. "
            f"Expected lowercase dotted-hyphenated form, e.g. 'runtime.application-host'.",
            value=value,
            location=where,
        )


@dataclass(frozen=True)
class CompositionConfig:
    """Validated `roots` + `bindings`. Construction implies the schema passed."""

    roots: tuple[ServiceId, ...]
    bindings: dict[ServiceId, ImplementationId]


def parse_composition_config(raw: Any, *, namespace: str = CONFIG_NAMESPACE) -> CompositionConfig:
    """Validate a loaded mapping into a `CompositionConfig`.

    Separated from loading so the schema can be tested without touching disk,
    and so callers holding an already-loaded mapping do not re-read it.

    `namespace` selects the top-level key a *second* composition root's config
    is nested under (e.g. `gateway-service-composition` for the gateway-service
    process root) -- distinct roots get distinct package-default/override files
    via `load_composition_config`'s own `namespace` parameter, so this only
    matters for a raw mapping passed directly in tests.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise composition_error(
            1,
            "Composition config root must be a mapping with 'roots' and 'bindings' keys.",
            actual_type=type(raw).__name__,
        )

    section = raw.get(namespace, raw)
    if not isinstance(section, dict):
        raise composition_error(
            1,
            "The 'composition' section must be a mapping with 'roots' and 'bindings' keys.",
            actual_type=type(section).__name__,
        )

    unknown = sorted(set(section) - {"roots", "bindings"})
    if unknown:
        raise composition_error(
            1,
            f"Unknown composition config key(s): {', '.join(unknown)}. "
            f"Only 'roots' and 'bindings' are supported.",
            unknown_keys=unknown,
        )

    raw_roots = section.get("roots") or []
    if not isinstance(raw_roots, list):
        raise composition_error(
            1,
            "Composition 'roots' must be a list of service identifiers.",
            actual_type=type(raw_roots).__name__,
        )

    raw_bindings = section.get("bindings") or {}
    if not isinstance(raw_bindings, dict):
        raise composition_error(
            1,
            "Composition 'bindings' must be a mapping of service-id to implementation-id.",
            actual_type=type(raw_bindings).__name__,
        )

    roots: list[ServiceId] = []
    for entry in raw_roots:
        if not isinstance(entry, str):
            raise composition_error(
                1,
                "Composition 'roots' entries must be strings.",
                actual_type=type(entry).__name__,
            )
        _reject_code_reference(entry, where="roots")
        if ServiceId(entry) in roots:
            raise composition_error(
                1, f"Duplicate composition root {entry!r}.", service_id=entry
            )
        roots.append(ServiceId(entry))

    bindings: dict[ServiceId, ImplementationId] = {}
    for service, implementation in raw_bindings.items():
        if not isinstance(service, str) or not isinstance(implementation, str):
            raise composition_error(
                1,
                "Composition 'bindings' must map string service-id to string implementation-id.",
                service_id=str(service),
            )
        _reject_code_reference(service, where="bindings key")
        _reject_code_reference(implementation, where=f"bindings[{service}]")
        bindings[ServiceId(service)] = ImplementationId(implementation)

    return CompositionConfig(roots=tuple(roots), bindings=bindings)


def load_composition_config(
    *,
    pkg_default_path: Path,
    project_root: Path | None = None,
    namespace: str = CONFIG_NAMESPACE,
) -> CompositionConfig:
    """Load and validate composition config across the three standard tiers.

    `namespace` also selects the override filename (`<namespace>.yaml` under
    the user-global and project-local config directories), so a second
    composition root's config never collides with the primary root's.
    """
    from audiagentic.foundation.config import load_layered_config

    raw = load_layered_config(
        pkg_default_path=pkg_default_path,
        project_root=project_root,
        namespace=namespace,
    )
    return parse_composition_config(raw, namespace=namespace)
