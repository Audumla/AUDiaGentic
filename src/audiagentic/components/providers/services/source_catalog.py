"""Normalized model-source catalog cache (MO12).

Provides static/list-api source catalogs, glob filtering, and cached
degradation for remote-account sources. Consumed by MO07 projection — this
module owns the network/cache boundary and NOTHING about provider config
rendering or key injection.

External failures follow arch-standards §8.1: classified as exactly one of
transient/configuration/authorization/contract; one bounded retry for
transient only; best-effort refresh degrades to the last-known-good cache
with ``action_needed`` and never fails the enclosing sync. Ordinary reconcile
performs no network call — fetchers run only on explicit ``refresh=True``.

The connector fetcher registry is genuine §2 data dispatch: the selection key
(``connector``) is a closed-enum value from source CONFIG with multiple
implementations, exactly like secret-ref schemes — not an indirection around
a single known callable.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.io import atomic_write_json, load_yaml_value
from audiagentic.foundation.paths.names import get_package_providers_config_dir
from audiagentic.foundation.registry_utils import Registry
from audiagentic.foundation.time import now_iso_z

_catalog_conflict = make_error_factory("CON", "SRCCAT", "providers")

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "model-source-catalog.schema.json"
)
_FETCH_TIMEOUT_SECONDS = 10.0

# fetcher(base_url, api_key) -> list of neutral model dicts (model-id, ...).
# api_key may be None; fetchers receive ONLY these two connectivity values.
SourceCatalogFetcher = Callable[[str, str | None], list[dict[str, Any]]]


@dataclass
class SourceCatalogResult:
    """Normalized catalog outcome for one source (MO12 step 1)."""

    source_id: str
    discovery_mode: str
    models: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: str | None = None
    freshness: str = "missing"  # "fresh" | "cached" | "missing"
    stale: bool = False
    failure_class: str | None = None
    error_code: str | None = None
    action_needed: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "discovery_mode": self.discovery_mode,
            "models": self.models,
            "fetched_at": self.fetched_at,
            "freshness": self.freshness,
            "stale": self.stale,
            "failure_class": self.failure_class,
            "error_code": self.error_code,
            "action_needed": self.action_needed,
        }


# --- validation ---------------------------------------------------------------


def _validate_catalog_payload(payload: Any, *, origin: str) -> dict[str, Any]:
    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = sorted(
        error.message for error in Draft202012Validator(schema).iter_errors(payload)
    )
    if issues:
        raise _catalog_conflict(
            1,
            "model-source catalog payload failed contract validation",
            origin=origin,
            issues=issues,
        )
    return payload


# --- static catalogs (data files, config-over-code) ----------------------------


def _static_catalog_path(source_id: str) -> Path:
    return get_package_providers_config_dir() / "model-catalogs" / f"{source_id}.yaml"


def load_static_catalog(source_id: str) -> list[dict[str, Any]]:
    """Load a curated static catalog data file; absence is a contract failure
    for a source that declares static-catalog discovery."""
    path = _static_catalog_path(source_id)
    payload = load_yaml_value(path, default=None)
    if payload is None:
        raise _catalog_conflict(
            1,
            "static catalog data file is missing for this source",
            origin=str(path),
        )
    return _validate_catalog_payload(payload, origin=str(path))["models"]


# --- list-api fetchers (connector registry) -------------------------------------


def _http_get_json(url: str, api_key: str | None) -> Any:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _normalize_openai_models(payload: Any) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise _catalog_conflict(2, "list-api response is not an OpenAI-style model list")
    models: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        model: dict[str, Any] = {"model-id": str(item["id"])}
        if item.get("name"):
            model["display-name"] = str(item["name"])
        context_length = item.get("context_length")
        if isinstance(context_length, int) and context_length >= 1:
            model["context-window"] = context_length
        models.append(model)
    return models


def _fetch_openai_compatible(base_url: str, api_key: str | None) -> list[dict[str, Any]]:
    base = base_url.rstrip("/")
    url = base if base.endswith("/v1") else f"{base}/v1"
    return _normalize_openai_models(_http_get_json(f"{url}/models", api_key))


def _fetch_openrouter(base_url: str, api_key: str | None) -> list[dict[str, Any]]:
    return _normalize_openai_models(
        _http_get_json(f"{base_url.rstrip('/')}/models", api_key)
    )


def _load_builtin_fetchers() -> None:
    # V1 scope (RV319): only the two connectors with confirmed list endpoints.
    # New connectors are one registration when MO09 verifies their endpoint.
    _fetchers.register("openai-compatible", _fetch_openai_compatible)
    _fetchers.register("openrouter", _fetch_openrouter)


_fetchers: Registry[SourceCatalogFetcher] = Registry(loader=_load_builtin_fetchers)


def register_catalog_fetcher(connector: str, fetcher: SourceCatalogFetcher, *, replace: bool = False) -> None:
    _fetchers.register(connector, fetcher, replace=replace)


# --- failure classification (arch-standards §8.1, table-driven) ------------------

_STATUS_CLASSES: dict[int, str] = {
    401: "authorization",
    403: "authorization",
    429: "transient",
}


def classify_remote_failure(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        by_status = _STATUS_CLASSES.get(exc.code)
        if by_status:
            return by_status
        return "transient" if exc.code >= 500 else "contract"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "transient"
    if isinstance(exc, (json.JSONDecodeError, AudiaGenticError)):
        return "contract"
    if isinstance(exc, ValueError):
        return "configuration"
    return "contract"


# --- cache ----------------------------------------------------------------------


def _cache_path(project_root: Path, source_id: str) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers" / "source-catalogs" / f"{source_id}.json"


def _read_cache(project_root: Path, source_id: str) -> dict[str, Any] | None:
    path = _cache_path(project_root, source_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _catalog_conflict(
            1,
            "cached model-source catalog is corrupt; refusing to use it",
            origin=str(path),
        ) from exc
    return _validate_catalog_payload(payload, origin=str(path))


def _write_cache(project_root: Path, source_id: str, models: list[dict[str, Any]]) -> str:
    fetched_at = now_iso_z()
    payload = {
        "contract-version": "v1",
        "source-id": source_id,
        "discovery-mode": "list-api",
        "fetched-at": fetched_at,
        "models": models,
    }
    _validate_catalog_payload(payload, origin="fetch-result")
    atomic_write_json(_cache_path(project_root, source_id), payload)
    return fetched_at


# --- filtering (pure) -------------------------------------------------------------


def apply_model_filter(
    models: list[dict[str, Any]], model_filter: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Include/exclude glob filter: exclude wins; empty include means all;
    stable sort by model id (MO12 step 5)."""
    include = list((model_filter or {}).get("include") or [])
    exclude = list((model_filter or {}).get("exclude") or [])

    def _included(model_id: str) -> bool:
        if exclude and any(fnmatch(model_id, pattern) for pattern in exclude):
            return False
        if not include:
            return True
        return any(fnmatch(model_id, pattern) for pattern in include)

    return sorted(
        (model for model in models if _included(model.get("model-id", ""))),
        key=lambda model: model.get("model-id", ""),
    )


# --- main entry --------------------------------------------------------------------


def _timeline(project_root: Path, source_id: str, event: str, attributes: dict[str, Any]) -> None:
    from audiagentic.foundation.observability import record_timeline_event

    record_timeline_event(
        project_root / ".audiagentic" / "runtime" / "providers" / "source-catalog-timeline.jsonl",
        component="providers",
        resource_kind="model-source-catalog",
        resource_id=source_id,
        event=event,
        attributes=attributes,
    )


def _refresh_from_list_api(
    project_root: Path, source_id: str, source: dict[str, Any]
) -> SourceCatalogResult:
    connector = source.get("connector", "")
    fetcher = _fetchers.get(connector)
    if fetcher is None:
        return _degraded(
            project_root, source_id,
            failure_class="configuration",
            error_code="CON-SRCCAT-002",
            action_needed=(
                f"no list-api fetcher exists for connector '{connector}'; "
                "use static-catalog or none discovery for this source"
            ),
        )

    base_url = source.get("base-url", "")
    api_key: str | None = None
    key_ref = source.get("api-key-ref")
    if key_ref:
        from audiagentic.foundation.secrets import resolve_secret_ref

        try:
            # Resolved only inside this call frame; passed to the fetcher and
            # retained nowhere (§8.1 redaction at the remote-call boundary).
            api_key = resolve_secret_ref(key_ref)
        except AudiaGenticError as exc:
            return _degraded(
                project_root, source_id,
                failure_class="authorization",
                error_code=exc.code,
                action_needed=f"secret reference {key_ref!r} could not be resolved; set the variable",
            )

    last_exc: Exception | None = None
    for attempt in range(2):  # §8.1: one bounded retry, transient only
        try:
            models = fetcher(base_url, api_key)
            break
        except Exception as exc:  # noqa: BLE001 — remote boundary
            last_exc = exc
            if classify_remote_failure(exc) != "transient" or attempt == 1:
                return _degraded(
                    project_root, source_id,
                    failure_class=classify_remote_failure(exc),
                    error_code="CON-SRCCAT-002",
                    action_needed=(
                        "model list fetch failed; check connectivity and credentials, "
                        "then re-run refresh"
                    ),
                )
    else:  # pragma: no cover — loop always breaks or returns
        raise AssertionError(last_exc)

    fetched_at = _write_cache(project_root, source_id, models)
    _timeline(project_root, source_id, "source-catalog.refreshed", {"count": len(models)})
    return SourceCatalogResult(
        source_id=source_id,
        discovery_mode="list-api",
        models=models,
        fetched_at=fetched_at,
        freshness="fresh",
    )


def _stale_age_seconds(fetched_at: str) -> int | None:
    from datetime import datetime, timezone

    try:
        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - fetched).total_seconds()))


def _degraded(
    project_root: Path,
    source_id: str,
    *,
    failure_class: str,
    error_code: str,
    action_needed: str,
) -> SourceCatalogResult:
    """Degrade to the last-known-good cache; missing when no cache exists."""
    cached = _read_cache(project_root, source_id)
    # Timeline attribute keys are kebab-case (timeline convention); the result
    # dataclass keeps the same facts as snake_case Python fields.
    attributes: dict[str, Any] = {
        "failure-class": failure_class,
        "error-code": error_code,
        "action-needed": action_needed,
        "fallback": "cached" if cached else "none",
        "stale": cached is not None,
    }
    fetched_at = cached.get("fetched-at") if cached else None
    if fetched_at:
        attributes["cached-fetched-at"] = fetched_at
        stale_age = _stale_age_seconds(fetched_at)
        if stale_age is not None:
            attributes["stale-age-seconds"] = stale_age
    _timeline(project_root, source_id, "source-catalog.degraded", attributes)
    if cached is None:
        return SourceCatalogResult(
            source_id=source_id,
            discovery_mode="list-api",
            freshness="missing",
            failure_class=failure_class,
            error_code=error_code,
            action_needed=action_needed,
        )
    return SourceCatalogResult(
        source_id=source_id,
        discovery_mode="list-api",
        models=cached.get("models", []),
        fetched_at=cached.get("fetched-at"),
        freshness="cached",
        stale=True,
        failure_class=failure_class,
        error_code=error_code,
        action_needed=action_needed,
    )


def get_source_catalog(
    project_root: Path,
    source_id: str,
    source: dict[str, Any],
    *,
    refresh: bool = False,
) -> SourceCatalogResult:
    """Return the normalized catalog for one source.

    ``refresh=False`` (the ordinary reconcile path) NEVER performs a network
    call: static catalogs load from data files, list-api sources read the
    cache, ``none`` discovery yields an empty result.
    """
    discovery = source.get("model-discovery", "none")

    if discovery == "static-catalog":
        models = load_static_catalog(source_id)
        return SourceCatalogResult(
            source_id=source_id,
            discovery_mode="static-catalog",
            models=models,
            freshness="fresh",
        )

    if discovery == "list-api":
        if refresh:
            return _refresh_from_list_api(project_root, source_id, source)
        cached = _read_cache(project_root, source_id)
        if cached is None:
            return SourceCatalogResult(
                source_id=source_id,
                discovery_mode="list-api",
                freshness="missing",
                action_needed="no cached catalog; run an explicit refresh for this source",
            )
        return SourceCatalogResult(
            source_id=source_id,
            discovery_mode="list-api",
            models=cached.get("models", []),
            fetched_at=cached.get("fetched-at"),
            freshness="cached",
        )

    return SourceCatalogResult(source_id=source_id, discovery_mode="none", freshness="missing")


__all__ = [
    "SourceCatalogResult",
    "apply_model_filter",
    "classify_remote_failure",
    "get_source_catalog",
    "load_static_catalog",
    "register_catalog_fetcher",
]
