"""Provider model catalog fetching."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from audiagentic.components.optional.providers.services.provider_catalog import (
    build_model_catalog,
    write_model_catalog,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from ..descriptors.registry import all_descriptors

_CATALOG_TIMEOUT = 10


def _call_with_timeout(fn, timeout: float) -> tuple[bool, Any]:
    """Call fn in a thread, return (success, result_or_exception)."""
    result: list[Any] = []
    exception: list[BaseException] = []

    def _target():
        try:
            result.append(fn())
        except BaseException as exc:  # noqa: BLE001
            exception.append(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        exception.append(TimeoutError(f"catalog fetch timed out after {timeout}s"))
    if exception:
        return False, exception[0]
    return True, result[0]


def fetch_provider_catalog(
    provider_id: str,
    *,
    project_root: Path,
    provider_config: dict[str, Any] | None = None,
    timeout: float = _CATALOG_TIMEOUT,
) -> dict[str, Any]:
    descriptors = all_descriptors()
    desc = descriptors.get(provider_id)
    if desc is None:
        raise AudiaGenticError(
            code="PRV-CATALOG-001",
            kind="not-found",
            message=f"no descriptor for provider {provider_id!r}",
            details={"provider-id": provider_id},
        )
    if desc.fetch_catalog_fn is None:
        raise AudiaGenticError(
            code="PRV-CATALOG-002",
            kind="not-supported",
            message=f"provider {provider_id!r} does not support catalog fetch",
            details={"provider-id": provider_id},
        )
    success, result_or_exc = _call_with_timeout(
        lambda: desc.fetch_catalog_fn(provider_config or {}),
        timeout=timeout,
    )
    if not success:
        raise AudiaGenticError(
            code="PRV-CATALOG-004",
            kind="timeout",
            message=f"catalog fetch timed out after {timeout}s for {provider_id!r}",
            details={"provider-id": provider_id},
        ) from result_or_exc
    models = result_or_exc
    if not models:
        raise AudiaGenticError(
            code="PRV-CATALOG-003",
            kind="empty",
            message=f"catalog fetch returned no models for {provider_id!r}",
            details={"provider-id": provider_id},
        )
    payload = build_model_catalog(provider_id=provider_id, models=models, source="cli")
    path = write_model_catalog(project_root, payload)
    return {"provider_id": provider_id, "model_count": len(models), "path": str(path), "ok": True}


def refresh_all_catalogs(*, project_root: Path) -> dict[str, Any]:
    results = []
    for provider_id, desc in sorted(all_descriptors().items()):
        if desc.fetch_catalog_fn is None:
            continue
        try:
            result = fetch_provider_catalog(provider_id, project_root=project_root)
        except Exception as exc:  # noqa: BLE001
            result = {"provider_id": provider_id, "ok": False, "error": str(exc)}
        results.append(result)
    return {"ok": all(r.get("ok") for r in results), "providers": results}
