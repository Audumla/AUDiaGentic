"""``audiagentic qualify``: prove the installed implementation and record it (CFG07).

For each selected provider and session surface the qualifier runs the
conformance checks that need no prompt and no network, then writes one local
platform record (``platform_records``). The record is what lets the surface
resolver accept a platform the vendor did not ship evidence for.

Checks, each reported with its outcome:

- ``implementation``: a provider that has a CLI must have it installed; its
  executable digest and version are part of the record's fingerprint.
- ``adapter``: the surface's adapter reference resolves to a callable.
- ``platform``: the running platform is the one being recorded.

A provider may add stronger probes later by registering them here; the record
format does not change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.runtime.system.platform import release_platform_name

from . import platform_records as records


def _checks(descriptor: Any, adapter_ref: str | None, fingerprint: dict[str, Any]) -> list[dict[str, Any]]:
    from ..lifecycle.lifecycle import probe_provider_cli

    checks: list[dict[str, Any]] = []
    if probe_provider_cli(descriptor) is None:
        checks.append({"name": "implementation", "ok": True, "detail": "no CLI to install"})
    else:
        digest = fingerprint.get("executable-digest")
        checks.append({
            "name": "implementation", "ok": bool(digest),
            "detail": f"executable {fingerprint.get('executable-version') or 'version unknown'}" if digest
            else "CLI not installed or its executable could not be located",
        })
    if adapter_ref:
        from ..session.session_surface_resolution import _adapter_factory_exists

        try:
            found = _adapter_factory_exists(adapter_ref)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            found, detail = False, str(error)
        else:
            detail = adapter_ref if found else f"{adapter_ref} does not resolve to a callable"
        checks.append({"name": "adapter", "ok": found, "detail": detail})
    return checks


def qualify(
    provider_id: str | None = None, surface_id: str | None = None, *, state_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Qualify the selected surfaces on this platform and return one summary per surface.

    Raises ``KeyError`` for an unknown provider or surface so the CLI can name it.
    """
    from ...descriptors.registry import all_descriptors

    descriptors = all_descriptors()
    if provider_id is not None and provider_id not in descriptors:
        raise KeyError(f"unknown provider {provider_id!r}")
    platform = release_platform_name()
    results: list[dict[str, Any]] = []
    for pid in sorted([provider_id] if provider_id else descriptors):
        descriptor = descriptors[pid]
        surfaces = [s for s in descriptor.session_surfaces if surface_id in (None, s.surface_id)]
        if surface_id is not None and provider_id is not None and not surfaces:
            raise KeyError(f"provider {pid!r} has no session surface {surface_id!r}")
        for surface in surfaces:
            adapter_ref = getattr(surface, "adapter_ref", None) or None
            fingerprint = records.current_fingerprint(pid, adapter_ref)
            record = records.build_record(
                provider_id=pid, surface_id=surface.surface_id, platform=platform,
                fingerprint=fingerprint, checks=_checks(descriptor, adapter_ref, fingerprint),
            )
            path = records.write_record(record, state_root)
            results.append({
                "provider": pid, "surface": surface.surface_id, "platform": platform,
                "result": record["result"], "path": str(path), "checks": record["checks"],
            })
    return results
