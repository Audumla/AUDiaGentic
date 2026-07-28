"""Provider model catalog fetching."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.output import ComponentOutputEvent, ComponentOutputSink

from ...descriptors.registry import all_descriptors
from ..config.provider_catalog import (
    build_model_catalog,
    write_model_catalog,
)


def _emit(output: ComponentOutputSink | None, message: str, level: str = "info") -> None:
    if output is not None:
        output(ComponentOutputEvent(message=message, kind="log", level=level))

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
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    descriptors = all_descriptors()
    desc = descriptors.get(provider_id)
    if desc is None:
        raise AudiaGenticError(
            code="RES-CAT-001",
            kind="providers",
            message=f"no descriptor for provider {provider_id!r}",
            details={"provider-id": provider_id},
        )
    if desc.fetch_catalog_fn is None:
        raise AudiaGenticError(
            code="CON-CAT-001",
            kind="providers",
            message=f"provider {provider_id!r} does not support catalog fetch",
            details={"provider-id": provider_id},
        )
    _emit(on_progress, f"Fetching model catalog for {provider_id} (timeout {timeout}s)...")
    success, result_or_exc = _call_with_timeout(
        lambda: desc.fetch_catalog_fn(provider_config or {}),
        timeout=timeout,
    )
    if not success:
        raise AudiaGenticError(
            code="TO-CAT-001",
            kind="providers",
            message=f"catalog fetch timed out after {timeout}s for {provider_id!r}",
            details={"provider-id": provider_id},
        ) from result_or_exc
    models = result_or_exc
    if not models:
        raise AudiaGenticError(
            code="RES-CAT-002",
            kind="providers",
            message=f"catalog fetch returned no models for {provider_id!r}",
            details={"provider-id": provider_id},
        )
    payload = build_model_catalog(provider_id=provider_id, models=models, source="cli")
    path = write_model_catalog(project_root, payload)
    _emit(on_progress, f"{provider_id}: {len(models)} model(s) written to {path.name}")
    return {"provider_id": provider_id, "model_count": len(models), "path": str(path), "ok": True}


def refresh_all_catalogs(
    *,
    project_root: Path,
    on_progress: ComponentOutputSink | None = None,
) -> dict[str, Any]:
    eligible = [(pid, desc) for pid, desc in sorted(all_descriptors().items()) if desc.fetch_catalog_fn is not None]
    total = float(len(eligible))
    results = []
    for i, (provider_id, _) in enumerate(eligible):
        if on_progress is not None:
            on_progress(ComponentOutputEvent(
                message=f"[{provider_id}] fetching catalog ({i + 1}/{int(total)})",
                progress=float(i + 1),
                total=total,
            ))
        try:
            result = fetch_provider_catalog(provider_id, project_root=project_root, on_progress=on_progress)
        except Exception as exc:  # noqa: BLE001
            _emit(on_progress, f"{provider_id}: failed — {exc}", level="warning")
            result = {"provider_id": provider_id, "ok": False, "error": str(exc)}
        results.append(result)
    _emit(on_progress, f"Catalog refresh complete — {sum(1 for r in results if r.get('ok'))} / {len(results)} succeeded")
    return {"ok": all(r.get("ok") for r in results), "providers": results}
