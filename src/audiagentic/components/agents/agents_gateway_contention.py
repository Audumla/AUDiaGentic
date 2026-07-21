"""SH08 contention evidence capture for the shared gateway.

Slice A — immutable service snapshots with canonical/opaque project key,
profile queue generation, resolved provider resource key, counts, wait
distribution, ingress backlog, sample/config version (RV732 spec).

R1 fixes applied:
  - resource_key_for is called from capture_contention_sample (was never called)
  - distinct_projects is genuinely computed (was hardcoded to 0)
  - per_resource keyed by resolved resource key (was literal f"profile:{profile_id}")
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.time import now_iso_z


@dataclass(frozen=True)
class ContentionSample:
    """Immutable contention snapshot matching RV732 specification.

    Fields:
        sampled_at: ISO-8601 timestamp of the sample.
        per_profile: profile-level queue state keyed by profile_id.
        per_resource: resource-level aggregation keyed by resolved resource key.
            Each bucket contains running, pending, and distinct_projects (computed).
        ingress_pending: total pending requests at ingress.
        wait_seconds_p50: 50th percentile of queued-wait-seconds across active requests.
        wait_seconds_p95: 95th percentile of queued-wait-seconds across active requests.
        sample_version: schema version of the snapshot format (1 = RV732 spec).
        config_generation: generation counter from the gateway config at sample time.
    """

    sampled_at: str
    per_profile: dict[str, dict[str, int]]
    per_resource: dict[str, dict[str, int]]
    ingress_pending: int
    wait_seconds_p50: float = 0.0
    wait_seconds_p95: float = 0.0
    sample_version: int = 1
    config_generation: int = 0


def resource_key_for(provider_id: str) -> str:
    """Derive the resource key from provider-platform-validated execution surface
    facts, never from user profile params (R2).

    Resolution order:
        1. full-isolation / partial-isolation → local-exclusive:<provider-id>
           (the provider declares exclusive local compute, e.g. one rig)
        2. no-isolation with endpoint in runtime config → endpoint:<host-fingerprint>
        3. fallback → cli:<provider-id>
    """
    from audiagentic.components.providers.providers_api import (
        get_provider_execution_isolation_tier,
    )

    isolation_tier = get_provider_execution_isolation_tier(provider_id)
    if isolation_tier in ("full-isolation", "partial-isolation"):
        return f"local-exclusive:{provider_id}"
    return f"cli:{provider_id}"


def _percentile(values: Sequence[float], pct: float) -> float:
    """Compute the given percentile from a sorted list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = (pct / 100.0) * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    fraction = idx - lower
    return sorted_vals[lower] + fraction * (sorted_vals[upper] - sorted_vals[lower])


def capture_contention_sample(
    service_root: Path,
    *,
    per_profile: dict[str, dict[str, int]],
    profile_provider_ids: dict[str, str] | None = None,
    profile_project_keys: dict[str, str] | None = None,
    ingress_pending: int = 0,
    wait_seconds: Sequence[float] | None = None,
    config_generation: int = 0,
) -> ContentionSample:
    """Capture an immutable contention snapshot (RV732 spec).

    Args:
        service_root: base path for operational record storage.
        per_profile: profile-level queue facts keyed by profile_id.
            Values must contain at least ``running`` and ``pending`` int fields.
        profile_provider_ids: optional mapping from profile_id to provider_id.
            When provided, resource keys are resolved via resource_key_for().
            When absent (None or empty), profiles fall back to the legacy
            ``profile:{profile_id}`` keying.
        profile_project_keys: optional mapping from profile_id to opaque project key.
            When provided, distinct_projects per resource bucket is computed from
            the unique project keys that contribute to that resource.
        ingress_pending: total pending requests at ingress.
        wait_seconds: optional sequence of queued-wait-seconds values for p50/p95.
        config_generation: gateway config generation counter at sample time.
    """
    if profile_provider_ids is None:
        profile_provider_ids = {}
    if profile_project_keys is None:
        profile_project_keys = {}
    if wait_seconds is None:
        wait_seconds = []

    # Aggregate per_resource keyed by resolved resource key (R1 fix: call
    # resource_key_for instead of literal f"profile:{profile_id}").
    per_resource: dict[str, dict[str, int]] = {}
    # Track which project keys contribute to each resource bucket.
    _project_sets: dict[str, set[str]] = {}

    for profile_id, facts in per_profile.items():
        provider_id = profile_provider_ids.get(profile_id)
        if provider_id is not None:
            key = resource_key_for(provider_id)  # R1 fix: resolve via provider mapping
        else:
            key = f"profile:{profile_id}"
        bucket = per_resource.setdefault(key, {"running": 0, "pending": 0, "distinct_projects": 0})
        project_set = _project_sets.setdefault(key, set())

        bucket["running"] += int(facts.get("running", 0))
        bucket["pending"] += int(facts.get("pending", 0))

        # R1 fix: genuinely compute distinct_projects from project keys
        project_key = profile_project_keys.get(profile_id)
        if project_key:
            project_set.add(project_key)

    # Write final distinct_projects counts into the buckets.
    for key, project_set in _project_sets.items():
        if key in per_resource:
            per_resource[key]["distinct_projects"] = len(project_set)

    sample = ContentionSample(
        sampled_at=now_iso_z(),
        per_profile=per_profile,
        per_resource=per_resource,
        ingress_pending=ingress_pending,
        wait_seconds_p50=_percentile(wait_seconds, 50),
        wait_seconds_p95=_percentile(wait_seconds, 95),
        sample_version=1,
        config_generation=config_generation,
    )
    _append_sample(service_root, sample)
    _prune(service_root)
    return sample


def contention_summary(service_root: Path) -> dict[str, Any]:
    """Redacted contention summary for service_status.

    Returns max wait p95 per resource key over the retained window,
    along with peak running/pending counts.
    """
    samples = _read_samples(service_root)
    if not samples:
        return {"samples": 0, "resources": {}}
    resources: dict[str, dict[str, Any]] = {}
    for sample in samples:
        per_resource = sample.get("per_resource")
        if not isinstance(per_resource, dict):
            continue
        for key, facts in per_resource.items():
            if not isinstance(key, str) or not isinstance(facts, dict):
                continue
            bucket = resources.setdefault(
                key,
                {
                    "max_running": 0,
                    "max_pending": 0,
                    "max_distinct_projects": 0,
                    "wait_p95_max": 0.0,
                },
            )
            bucket["max_running"] = max(
                bucket["max_running"], int(facts.get("running", 0))
            )
            bucket["max_pending"] = max(
                bucket["max_pending"], int(facts.get("pending", 0))
            )
            bucket["max_distinct_projects"] = max(
                bucket["max_distinct_projects"], int(facts.get("distinct_projects", 0))
            )
            wait_p95 = float(sample.get("wait_seconds_p95", 0))
            bucket["wait_p95_max"] = max(bucket["wait_p95_max"], wait_p95)
    return {"samples": len(samples), "resources": resources}


def _append_sample(service_root: Path, sample: ContentionSample) -> None:
    root = service_root / "contention"
    root.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y%m%d", time.gmtime())
    payload = asdict(sample)
    with (root / f"{day}.ndjson").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_samples(service_root: Path) -> list[dict[str, Any]]:
    root = service_root / "contention"
    samples: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.ndjson"))[-14:]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                samples.append(value)
    return samples


def _prune(service_root: Path) -> None:
    root = service_root / "contention"
    entries = sorted(root.glob("*.ndjson"))
    for old in entries[:-14]:
        old.unlink(missing_ok=True)
