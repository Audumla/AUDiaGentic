"""``audiagentic qualify --live PROVIDER``: run a provider's native probes and record SH53 evidence (CFG12).

Deliberately small: a static dispatch table, one bounded outcome per capability, and the existing
evidence authority. A probe runs against a DISPOSABLE environment it builds itself; the runner never
touches a production session. A capability is true only when a probe proved it; a probe that fails,
times out or was not written leaves it false with a registered reason (unknown is unproven, a timeout
is never proof of absence). The record is ``supported`` only when the strict join requirements are all
proven (join_readiness), otherwise ``partial``/``unsupported``/``inconclusive``. Proof is protocol
evidence for the exact executable, adapter and schema: it never says anything about a vendor model.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import evidence

QUALIFIER_VERSION = "1"
CAPABILITIES = (
    "passive-identity", "existing-session-attach", "conditional-admission", "correlated-result",
    "safe-detach", "reconnect", "concurrent-human-use",
)
# What the strict join needs (join_readiness): both prerequisites, the three mandatory claims and one
# concurrency-safe admission.
_REQUIRED = ("passive-identity", "existing-session-attach", "safe-detach", "conditional-admission", "correlated-result")
_REASON_FAILED, _REASON_UNPROVEN = "probe-failed", "unproven"


@dataclass(frozen=True)
class ProbeOutcome:
    """One capability's verdict: proven, or why not. Observations are bounded and carry no payloads."""

    capability: str
    proven: bool
    reason: str | None = None
    observations: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveContext:
    root: Path
    facts: dict[str, Any]


@dataclass(frozen=True)
class LiveTarget:
    surface_id: str
    native_protocol: str
    endpoint_kind: str
    fixture_id: str
    adapter_ref: str
    probe_ref: str


#: Providers with native probes. Static on purpose: a new provider is a deliberate addition.
LIVE_TARGETS: dict[str, LiveTarget] = {
    "codex": LiveTarget(
        surface_id="codex-app-server", native_protocol="codex-app-server-jsonrpc-ws", endpoint_kind="socket",
        fixture_id="codex-app-server-disposable",
        adapter_ref="audiagentic.components.providers.adapters.codex.join:AppServerClient",
        probe_ref="audiagentic.components.providers.services.qualification.probes.codex:run",
    ),
}


def _state(proven: set[str], reasons: list[str]) -> str:
    """supported only when the strict join is fully proven; partial when something is; otherwise the
    reasons decide: explicitly unsupported capabilities are ``unsupported``, anything else (failed or
    never attempted) is ``inconclusive``, never a claim about the harness."""
    if all(name in proven for name in _REQUIRED) and ("concurrent-human-use" in proven or "conditional-admission" in proven):
        return "supported"
    if proven:
        return "partial"
    return "unsupported" if reasons and all(reason.startswith("unsupported") for reason in reasons) else "inconclusive"


def qualify_live(provider_id: str, *, state_root: Path | None = None) -> dict[str, Any]:
    """Run the provider's live probes in a disposable environment and write one immutable evidence record."""
    from audiagentic.foundation.config.refs import resolve_ref

    from ..session.join_readiness import adapter_identity

    target = LIVE_TARGETS.get(provider_id)
    if target is None:
        raise KeyError(f"provider {provider_id!r} has no live qualification probes")
    facts = evidence.inventory(provider_id)
    if not facts.get("executable-digest") or not facts.get("executable-version"):
        raise RuntimeError(f"{provider_id} is not installed or its version cannot be read; nothing to qualify")
    adapter = adapter_identity(target.adapter_ref)
    if adapter is None:
        raise RuntimeError(f"{target.adapter_ref} does not declare JOIN_ADAPTER")
    probe = resolve_ref(target.probe_ref)
    root = Path(tempfile.mkdtemp(prefix="qualify-live-"))
    cleanup_error: str | None = None
    try:
        try:
            outcomes = list(probe(LiveContext(root=root, facts=facts)))
        except Exception as error:  # noqa: BLE001 - a crashed probe proves nothing; it is reported, not raised
            outcomes = [ProbeOutcome(name, False, _REASON_FAILED, {"error": type(error).__name__}) for name in CAPABILITIES]
    finally:
        try:
            shutil.rmtree(root)
        except OSError as error:
            cleanup_error = f"{type(error).__name__}"
    by_name = {outcome.capability: outcome for outcome in outcomes}
    capabilities = {name: bool(by_name.get(name) and by_name[name].proven) for name in CAPABILITIES}
    proven = {name for name, value in capabilities.items() if value}
    reasons = sorted({(by_name.get(name).reason if by_name.get(name) and by_name[name].reason else _REASON_UNPROVEN)
                      for name in CAPABILITIES if name not in proven})
    state = _state(proven, reasons)
    observations = {name: (by_name[name].observations if name in by_name else {}) for name in CAPABILITIES}
    canonical = json.dumps({"capabilities": capabilities, "observations": observations}, sort_keys=True,
                           separators=(",", ":"), default=str).encode()
    suite_digest = evidence.file_digest(Path(inspect.getsourcefile(probe)))
    record = evidence.build_record(
        producer={"component": "providers", "qualifier-version": QUALIFIER_VERSION,
                  "suite-digest": suite_digest, "adapter-id": adapter.adapter_id, "adapter-version": "1",
                  "adapter-digest": adapter.adapter_digest},
        target={"provider-id": provider_id, "surface-id": target.surface_id, "platform": facts["platform"],
                "executable-version": facts["executable-version"], "executable-digest": facts["executable-digest"],
                "native-protocol": target.native_protocol, "native-schema-version": adapter.native_schema_version,
                "endpoint-kind": target.endpoint_kind},
        qualification={"state": state, "capabilities": capabilities, "unsupported-reasons": reasons},
        proof={"fixture-id": target.fixture_id, "test-run-id": "run-" + uuid.uuid4().hex[:12],
               "artifact-digest": "sha256:" + hashlib.sha256(canonical).hexdigest(),
               "verified-at": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
    )
    path = evidence.write_evidence(record, state_root=state_root)
    return {"provider": provider_id, "surface": target.surface_id, "state": state, "capabilities": capabilities,
            "reasons": reasons, "evidence-id": record["evidence-id"], "path": str(path),
            "observations": observations, "cleanup-error": cleanup_error,
            "claim": "native protocol behaviour of this exact executable, adapter and schema on a disposable "
                     "environment; not vendor-model, authentication or human-UI proof"}
