"""SH08 contention evidence capture for the shared gateway."""
from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.foundation.time import now_iso_z


@dataclass(frozen=True)
class ContentionSample:
    sampled_at: str
    per_profile: dict[str, dict[str, int]]
    per_resource: dict[str, dict[str, int]]
    ingress_pending: int


def resource_key_for(profile: Mapping[str, Any]) -> str:
    provider_id = str(profile.get("provider_id") or profile.get("provider-id") or "unknown")
    params = profile.get("params")
    facts = params if isinstance(params, Mapping) else {}
    endpoint = facts.get("endpoint-host-fingerprint")
    if isinstance(endpoint, str) and endpoint:
        return f"endpoint:{endpoint}"
    if facts.get("exclusive-local-compute") is True:
        return f"local-exclusive:{provider_id}"
    return f"cli:{provider_id}"


def capture_contention_sample(
    service_root: Path,
    *,
    per_profile: dict[str, dict[str, int]],
    ingress_pending: int = 0,
) -> ContentionSample:
    per_resource: dict[str, dict[str, int]] = {}
    for profile_id, facts in per_profile.items():
        key = f"profile:{profile_id}"
        bucket = per_resource.setdefault(key, {"running": 0, "pending": 0, "distinct_projects": 0})
        bucket["running"] += int(facts.get("running", 0))
        bucket["pending"] += int(facts.get("pending", 0))
    sample = ContentionSample(
        sampled_at=now_iso_z(),
        per_profile=per_profile,
        per_resource=per_resource,
        ingress_pending=ingress_pending,
    )
    _append_sample(service_root, sample)
    _prune(service_root)
    return sample


def contention_summary(service_root: Path) -> dict[str, Any]:
    samples = _read_samples(service_root)
    if not samples:
        return {"samples": 0, "resources": {}}
    resources: dict[str, dict[str, int]] = {}
    for sample in samples:
        per_resource = sample.get("per_resource")
        if not isinstance(per_resource, dict):
            continue
        for key, facts in per_resource.items():
            if not isinstance(key, str) or not isinstance(facts, dict):
                continue
            bucket = resources.setdefault(key, {"max_running": 0, "max_pending": 0})
            bucket["max_running"] = max(bucket["max_running"], int(facts.get("running", 0)))
            bucket["max_pending"] = max(bucket["max_pending"], int(facts.get("pending", 0)))
    return {"samples": len(samples), "resources": resources}


def _append_sample(service_root: Path, sample: ContentionSample) -> None:
    root = service_root / "contention"
    root.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y%m%d", time.gmtime())
    payload = {
        "sampled_at": sample.sampled_at,
        "per_profile": sample.per_profile,
        "per_resource": sample.per_resource,
        "ingress_pending": sample.ingress_pending,
    }
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
