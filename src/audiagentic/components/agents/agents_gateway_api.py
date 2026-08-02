"""Agent LLM Gateway public API — async submit, blocking run, status, wait, cancel.

Thin orchestration over agents_gateway_store (persistence), agents_gateway_queue
(per-profile concurrency), and agents_gateway_dispatch (provider dispatch/retry/
fallback). One GatewayQueueManager instance per process (module-level) — see
its docstring for the process-lifetime caveat.

SH02: submit_llm_request now validates through SubmissionEnvelope and persists a
redacted ExecutionManifest alongside each request record. The raw prompt body is
never persisted (only its digest); it is threaded to dispatch via functools.partial.
"""

from __future__ import annotations

import functools
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_dispatch as dispatch
from audiagentic.components.agents import agents_gateway_queue as queue_mod
from audiagentic.components.agents import agents_gateway_store as store

# A blocking wait with no requested timeout still needs a bound so it cannot
# hang forever; callers that want longer pass an explicit timeout_seconds.
DEFAULT_BLOCKING_TIMEOUT_SECONDS = 300.0

_QUEUE_MANAGER = queue_mod.GatewayQueueManager()


def _resolve_profile_for_submit(project_root: Path, agent_profile_id: str | None) -> dict[str, Any]:
    from audiagentic.components.agents.agents_api import resolve_default_profile, resolve_profile

    if agent_profile_id:
        return resolve_profile(project_root, agent_profile_id)
    return resolve_default_profile(project_root)


def _resolve_provider_isolation_tier(provider_id: str) -> str:
    """Resolve the required MA20 provider-level execution isolation fact."""
    from audiagentic.components.providers.providers_api import (
        get_provider_execution_isolation_tier,
    )

    return get_provider_execution_isolation_tier(provider_id)


def _classify_terminal_quality(
    project_root: Path,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Classify terminal output quality and return report dict, or None for non-terminal.

    Invokes agents_terminal_quality.classify_terminal_output only for records in
    TERMINAL_STATES. Gathers session-side evidence (latest-turn projection and
    quality summary) when a session is attached, but never mutates the record
    or persists any data.
    """
    if record["state"] not in store.TERMINAL_STATES:
        return None
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_terminal_quality import classify_terminal_output

    session_id = record.get("session-id")
    request_id = record.get("request-id")
    latest_turn: dict[str, Any] | None = None
    quality_summary: dict[str, Any] | None = None
    if session_id:
        latest_turn = session_store.latest_turn_projection(
            project_root,
            session_id,
            request_id=request_id,
        )
        quality_summary = session_store.latest_turn_quality_summary(
            project_root,
            session_id,
            request_id=request_id,
        )
    report = classify_terminal_output(
        record=record,
        latest_turn=latest_turn,
        session_event_summary=quality_summary,
    )
    return report.to_dict()


def _session_progress_context(
    project_root: Path, record: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (latest_session_event, progress_summary) for a record's session.

    Both are bounded, redacted projections built from the persisted session
    timeline — no prompt text, tool args, output, provider refs, or project
    roots. Returns (None, None) when the record has no session or no timeline
    exists yet (e.g. before the first turn event lands).
    """
    session_id = record.get("session-id")
    if not session_id:
        return None, None
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store

    request_id = record.get("request-id")
    latest_turn = session_store.latest_turn_projection(
        project_root,
        session_id,
        request_id=request_id,
    )
    progress_summary = session_store.build_session_progress_summary(
        project_root,
        session_id,
        request_id,
    )
    return latest_turn, progress_summary


def _request_progress(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """SH15: bounded progress projection for one request, including the
    richer session-evidence fields when a session is attached."""
    from audiagentic.components.agents.agents_gateway_progress import (
        project_request_progress,
    )

    latest_session_event, progress_summary = _session_progress_context(project_root, record)
    return project_request_progress(
        record,
        latest_session_event=latest_session_event,
        progress_summary=progress_summary,
    )


_PROCESS_INSTANCE_ID: str | None = None
_STARTED_AT: str | None = None


def _init_process_identity() -> None:
    """Generate process identity at module load (gateway startup)."""
    global _PROCESS_INSTANCE_ID, _STARTED_AT
    if _PROCESS_INSTANCE_ID is None:
        import uuid
        from datetime import datetime, timezone

        _PROCESS_INSTANCE_ID = uuid.uuid4().hex
        _STARTED_AT = datetime.now(timezone.utc).isoformat()


def _runtime_fingerprint() -> dict[str, str]:
    """Redacted runtime identity for operator diagnostics.

    Replaces the former Git-based source-stamp with process lifecycle identity:
    - runtime-version: installed package version (always present)
    - build-id: optional immutable identifier embedded at wheel/container build time
    - process-instance-id: random identifier generated once at gateway startup
    - started-at: ISO timestamp when this process began
    - owner-epoch: managed-service ownership generation (when available)

    This answers the actual operational questions:
    - Which build is installed? → runtime-version (+ build-id if present)
    - Is this still the old running process? → process-instance-id + started-at
    - Did ownership transfer or restart? → owner-epoch change

    No Git dependency — works in wheel installs, non-Git projects, containers.
    """
    _init_process_identity()
    from audiagentic import __version__

    result: dict[str, str] = {
        "runtime-version": __version__,
        "process-instance-id": _PROCESS_INSTANCE_ID or "unknown",
        "started-at": _STARTED_AT or "unknown",
    }

    # Optional build-id from embedded package metadata (PEP 639 / custom)
    try:
        import importlib.metadata as meta

        dist = meta.distribution("audiagentic")
        md = dist.metadata
        for key in ("build-id", "Build-Id", "X-Build-Id"):
            val = md.get(key)
            if val:
                result["build-id"] = val
                break
    except Exception:
        pass  # build-id is optional — absent is fine

    return result


def _enrich_terminal_result(
    result: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Add terminal-quality to a copy of *result* when the state is terminal.

    Returns the original *result* unchanged when non-terminal (no copy made).
    """
    if result["state"] in store.TERMINAL_STATES:
        enriched = dict(result)
        tq = _classify_terminal_quality(project_root, enriched)
        if tq is not None:
            enriched["terminal-quality"] = tq
        return enriched
    return result


def submit_llm_request(
    project_root: Path,
    *,
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    mode: str = "async",
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
    component_profile: str | None = None,
    _dispatch_owner_epoch: str | None = None,
    _dispatch_service_root: str | None = None,
) -> dict[str, Any]:
    """Submit a gateway request. Returns immediately with request-id and initial state
    unless mode='blocking', in which case it waits for a terminal result (see run_llm_request).

    Sessions (plan agent-sessions): ``session_keep_alive=True`` opens a live
    agent session that survives this request — the response's ``session-id``
    continues the conversation via ``session_id=...`` on later requests.
    Sessions are bound to one profile and self-clean:
    idle timeout (default 15 min) and max lifetime (default 4 h), both
    settable at open time — 0 disables that bound (long-lived remote-control
    sessions). Turns on one session queue FIFO; the reaper never closes a
    session that is processing or has queued turns. Close explicitly with
    close_llm_session when done.

    SH02: validates through SubmissionEnvelope, resolves an ExecutionManifest,
    and persists only a redacted record (prompt_digest, not raw prompt_body).
    The raw prompt is threaded to dispatch via functools.partial.
    """
    from audiagentic.components.agents.contracts.execution_context import (
        SubmissionEnvelope,
        build_manifest,
        compute_agent_runtime_digest,
        derive_idempotency_key,
        sanitize_submission_metadata,
    )
    from audiagentic.foundation.paths.names import get_active_profile
    from audiagentic.foundation.time import now_iso_z

    # --- 1. Construct and validate the submission envelope -----------------
    if component_profile is None:
        component_profile = get_active_profile()
    # Validate the caller-owned mapping before reading its control fields.
    # The sanitized form is the only metadata allowed into durable records,
    # lifecycle events, and provider packets.
    persisted_metadata = sanitize_submission_metadata(metadata)
    raw_metadata = dict(metadata or {})
    envelope_mapping = {
        "project_root": str(project_root),
        "schema_version": raw_metadata.get("schema_version", 1),
        "idempotency_key": raw_metadata.get("idempotency_key"),
        "correlation_id": raw_metadata.get("correlation_id"),
        "source": source,
        "agent_profile_id": agent_profile_id,
        "provider_id": raw_metadata.get("provider_id"),
        "model_id": raw_metadata.get("model_id"),
        "component_profile": component_profile,
        "mode": mode,
        "timeout_seconds": timeout_seconds,
        "session": {
            "session_id": session_id,
            "keep_alive": session_keep_alive,
            "idle_timeout_seconds": session_idle_timeout_seconds,
            "max_lifetime_seconds": session_max_lifetime_seconds,
        },
        "prompt_body": prompt_body,
        "metadata": raw_metadata,
    }
    envelope = SubmissionEnvelope.from_mapping(envelope_mapping)
    canonical_root = envelope.validate()

    # --- 2. Resolve profile ------------------------------------------------
    profile = _resolve_profile_for_submit(project_root, agent_profile_id)
    resolved_profile_id = profile["profile_id"]
    resolved_provider_id = profile["provider_id"]
    resolved_model_id = profile["model_id"]
    params = profile.get("params", {})

    # SH07 C2: when a gateway-owned registry is installed (shared mode), it
    # is authoritative for provider/model/queue-limits — project-local
    # profile data only selects which gateway profile id to reference. The
    # resolved snapshot is persisted on the record so the queue can validate
    # staleness on reload (CON-AGW-101) without re-deriving from mutable
    # caller params. In embedded mode (no registry installed) this stays
    # None; the queue's own embedded-compatibility fallback covers that case.
    from audiagentic.components.agents import agents_gateway_profiles as profiles_mod

    gateway_snapshot = None
    gateway_registry = profiles_mod.get_gateway_registry()
    if gateway_registry is not None:
        gateway_snapshot = gateway_registry.resolve_snapshot(resolved_profile_id)
        resolved_provider_id = gateway_snapshot.provider_id
        resolved_model_id = gateway_snapshot.model_id
        params = dict(gateway_snapshot.execution_params)

    # --- 3. Resolve provider isolation tier and runtime digest --------------
    isolation_tier = _resolve_provider_isolation_tier(resolved_provider_id)

    # Agent runtime digest: hash of resolved profile + provider config + component overlay
    from audiagentic.components.providers.providers_api import (
        get_provider_runtime_config_state,
    )

    provider_cfg = get_provider_runtime_config_state(
        project_root,
        resolved_provider_id,
    )
    agent_runtime_digest = compute_agent_runtime_digest(
        resolved_profile=profile,
        provider_config_state=provider_cfg,
        component_overlay={"component-profile": component_profile or ""},
    )

    # --- 4. Build the execution manifest -----------------------------------
    request_id = store.generate_request_id()
    manifest_id = f"mf_{uuid.uuid4().hex[:16]}"
    resolved_at = now_iso_z()
    manifest = build_manifest(
        envelope,
        manifest_id=manifest_id,
        request_id=request_id,
        resolved_at=resolved_at,
        canonical_root=canonical_root,
        agent_profile_id=resolved_profile_id,
        provider_id=resolved_provider_id,
        model_id=resolved_model_id,
        provider_isolation_tier=isolation_tier,
        agent_runtime_digest=agent_runtime_digest,
    )

    # Derive idempotency key (client-supplied wins, else deterministic)
    idempotency_key = derive_idempotency_key(
        envelope.idempotency_key,
        context_fingerprint=manifest.context_fingerprint,
        prompt_digest=manifest.prompt_digest,
        session_id=session_id,
    )

    # --- 5. Build and atomically admit the record ---------------------------
    # The client key currently arrives through transport metadata. It remains
    # available for envelope validation but must never reach records, queues,
    # events, or provider packets in raw form.
    record = store.build_record(
        request_id=request_id,
        agent_profile_id=resolved_profile_id,
        prompt_body=prompt_body,  # carried in-memory; redacted before persistence
        mode=mode,
        timeout_seconds=timeout_seconds,
        source=source,
        metadata=persisted_metadata,
        session_id=session_id,
        session_keep_alive=session_keep_alive,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        session_max_lifetime_seconds=session_max_lifetime_seconds,
        # Manifest fields (persisted)
        manifest_id=manifest_id,
        context_fingerprint=manifest.context_fingerprint,
        prompt_digest=manifest.prompt_digest,
        idempotency_key=None,
        correlation_id=envelope.correlation_id,
        # SH07 C2: gateway profile snapshot identity, resolved above.
        gateway_profile_id=gateway_snapshot.profile_id if gateway_snapshot else None,
        gateway_profile_generation=gateway_snapshot.generation if gateway_snapshot else None,
        gateway_profile_config_digest=gateway_snapshot.config_digest if gateway_snapshot else None,
        gateway_execution_lane_key=(
            gateway_snapshot.lane_key().public_id() if gateway_snapshot else None
        ),
        resolved_provider_id=resolved_provider_id,
        resolved_model_id=resolved_model_id,
        resolved_queue_limits=(
            {
                "max-concurrency": gateway_snapshot.max_concurrency,
                "queue-max-size": gateway_snapshot.queue_max_size,
            }
            if gateway_snapshot
            else None
        ),
        admission_policy_digest=(
            gateway_snapshot.admission_policy_digest if gateway_snapshot else None
        ),
    )
    record, created = store.admit_record(
        project_root,
        record,
        idempotency_key=idempotency_key,
        # C7: without this, the admission-phase work-index entry (which
        # recovery relies on to discover admitted-but-unclaimed requests
        # after a crash) is never written — service_root defaults to None
        # inside admit_record and the write is silently skipped.
        service_root=Path(_dispatch_service_root) if _dispatch_service_root else None,
    )

    if created:
        store.record_gateway_timeline(
            project_root,
            request_id,
            "request.created",
            state=record["state"],
            attributes={
                "agent-profile-id": resolved_profile_id,
                "mode": mode,
                "source": source,
                "correlation_id": envelope.correlation_id,
                "subject": persisted_metadata.get("subject"),
                "manifest-id": manifest_id,
                "context-fingerprint": manifest.context_fingerprint,
            },
        )

        # --- 6. Enqueue with dispatch_prompt threaded via functools.partial -
        runner = functools.partial(
            dispatch.dispatch_request,
            dispatch_prompt=prompt_body,
            manifest_id=manifest.manifest_id,
            context_fingerprint=manifest.context_fingerprint,
            component_profile=manifest.identity.component_profile,
            provider_isolation_tier=manifest.identity.provider_isolation_tier,
            worker_timeout_seconds=manifest.timeout_seconds or DEFAULT_BLOCKING_TIMEOUT_SECONDS,
        )
        record = _QUEUE_MANAGER.enqueue(
            project_root,
            record,
            params,
            runner,
            dispatch_owner_epoch=_dispatch_owner_epoch,
            dispatch_service_root=(
                Path(_dispatch_service_root) if _dispatch_service_root else None
            ),
        )

    if mode == "blocking":
        wait_timeout = timeout_seconds or DEFAULT_BLOCKING_TIMEOUT_SECONDS
        raw = _QUEUE_MANAGER.wait(project_root, record["request-id"], wait_timeout)
        return _enrich_terminal_result(raw, project_root)
    return record


def get_llm_request(project_root: Path, request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return store.read_public_status(project_root, request_id)


def request_runtime_status(project_root: Path, request_id: str) -> dict[str, Any]:
    """Return redacted runtime facts for one request without starting runtimes."""
    record = store.read_public_status(project_root, request_id)
    state = record["state"]
    slot = _QUEUE_MANAGER.request_slot_status(record["agent-profile-id"], request_id)
    if state in store.TERMINAL_STATES:
        queue_state = "terminal"
        profile_slot = None
    elif slot is not None:
        queue_state = "running" if slot in {"active", "idle"} else "queued"
        profile_slot = slot
    elif state == "running":
        queue_state = "running"
        profile_slot = "active"
    elif state == "queued" and record.get("dispatch-owner-epoch"):
        queue_state = "queued"
        profile_slot = "pending"
    else:
        queue_state = state
        profile_slot = None

    session_status: dict[str, Any] = {"available": False}
    session_id = record.get("session-id")
    if session_id:
        from audiagentic.components.agents.agents_gateway_sessions import peek_session_runtime

        runtime = peek_session_runtime()
        if runtime is not None:
            session_status = runtime.session_runtime_status(session_id)

    result: dict[str, Any] = {
        "request-id": request_id,
        "queue-state": queue_state,
        "profile-slot": profile_slot,
        "state": state,
        "cancel-requested": record.get("cancel-requested"),
        "cancel-acknowledged-by": record.get("cancel-acknowledged-by"),
        "session-id": session_id,
        "session": session_status,
        "progress": _request_progress(project_root, record),
    }
    if session_id:
        from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
        from audiagentic.components.agents import agents_gateway_sessions_store as session_store

        # AS33: read the raw session payload (schema-tolerant) so a
        # capability-snapshot field ahead of the formal schema isn't rejected.
        raw_session = session_store.read_session_record_raw(project_root, session_id)
        capabilities = binding_store.project_session_capabilities(raw_session)
        if capabilities is not None:
            result["capabilities"] = capabilities
    if state in store.TERMINAL_STATES:
        tq = _classify_terminal_quality(project_root, record)
        if tq is not None:
            result["terminal-quality"] = tq
    return result


def wait_llm_request(
    project_root: Path, request_id: str, timeout_seconds: float | None = None
) -> dict[str, Any]:
    """Block until a request reaches a terminal state or the timeout elapses.

    The caller's timeout is honoured; the MCP boundary applies its own transport
    cap. The MCP adapter applies its own transport-specific bound.
    Terminal results are enriched with ``terminal-quality``; timeout responses
    carry ``wait-timeout: True`` and omit it.
    """
    raw = _QUEUE_MANAGER.wait(
        project_root, request_id, timeout_seconds or DEFAULT_BLOCKING_TIMEOUT_SECONDS
    )
    if raw["state"] in store.TERMINAL_STATES:
        return _enrich_terminal_result(raw, project_root)
    # Non-terminal: timeout — signal it and omit terminal-quality
    result = dict(raw)
    result["wait-timeout"] = True
    result["progress"] = _request_progress(project_root, raw)
    return result


def cancel_llm_request(project_root: Path, request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested.

    See GatewayQueueManager.cancel — a running request is not force-terminated;
    its persisted terminal state reflects what actually happened.
    """
    record = store.read_record(project_root, request_id)
    return _QUEUE_MANAGER.cancel(project_root, record["agent-profile-id"], request_id)


def run_llm_request(
    project_root: Path,
    *,
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
    component_profile: str | None = None,
    _dispatch_owner_epoch: str | None = None,
    _dispatch_service_root: str | None = None,
) -> dict[str, Any]:
    """Submit and block until a terminal result or timeout. Not for event-triggered
    paths (AG12 handles those asynchronously through lifecycle events)."""
    return submit_llm_request(
        project_root,
        agent_profile_id=agent_profile_id,
        prompt_body=prompt_body,
        mode="blocking",
        timeout_seconds=timeout_seconds,
        source=source,
        metadata=metadata,
        session_id=session_id,
        session_keep_alive=session_keep_alive,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        session_max_lifetime_seconds=session_max_lifetime_seconds,
        component_profile=component_profile,
        _dispatch_owner_epoch=_dispatch_owner_epoch,
        _dispatch_service_root=_dispatch_service_root,
    )


def queue_status(agent_profile_id: str) -> dict[str, Any]:
    """Return queue depth/running/max-concurrency for one profile (used by AG13 status)."""
    return _QUEUE_MANAGER.queue_depth(agent_profile_id)


def gateway_status() -> dict[str, Any]:
    """Return queue depth/running/max-concurrency for every profile with an
    active queue in THIS process only (in-memory — empty after a restart even
    if persisted records exist). Prefer gateway_overview() for a complete
    picture; kept for backward compatibility with existing callers."""
    return _QUEUE_MANAGER.all_queue_depths()


def list_llm_requests(
    project_root: Path,
    *,
    state: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Reads from disk (agents_gateway_store.list_records), so this reflects
    requests from any process — including ones orphaned by a restart, unlike
    the in-memory-only queue_status/gateway_status (RV33 finding).
    """
    records = store.list_records(project_root)
    if state is not None:
        records = [r for r in records if r["state"] == state]
    records.sort(key=lambda r: r["created-at"], reverse=True)
    if limit is not None:
        records = records[:limit]
    return [
        store.project_public_status(
            record,
            latest_transition=store.latest_transition_projection(
                project_root, record["request-id"]
            ),
        )
        for record in records
    ]


def _public_session_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Redact a raw session record for client return: drop the internal
    provider-session-ref and project the binding through its public form."""
    from audiagentic.components.agents import agents_gateway_session_bindings as binding_store

    projected = dict(record)
    projected["binding"] = binding_store.public_binding_projection(record.get("binding"))
    projected.pop("provider-session-ref", None)
    return projected


def list_llm_sessions(
    project_root: Path,
    *,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """List persisted gateway sessions, newest first, with a 'live' flag for
    sessions whose transport is held by THIS process's SessionRuntime.

    Listing must never start a runtime as a side effect (peek only) — a
    session with no live handle in this process is simply reported as
    not-live, including the stale-non-live diagnostic when it was persisted
    active/non-terminal but nothing here is actually holding it.
    """
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_gateway_sessions import peek_session_runtime

    runtime = peek_session_runtime()
    live_ids = set(runtime.live_session_ids()) if runtime is not None else set()
    records = session_store.list_session_records(project_root)
    if state is not None:
        records = [r for r in records if r["state"] == state]
    records.sort(key=lambda r: r["created-at"], reverse=True)
    rows = []
    for record in records:
        live = record["session-id"] in live_ids
        row = {**_public_session_projection(record), "live": live}
        if not live and record["state"] not in session_store.SESSION_TERMINAL_STATES:
            row["runtime-state"] = "stale-non-live"
        rows.append(row)
    return rows


def close_llm_session(project_root: Path, session_id: str) -> dict[str, Any]:
    """Close a live session on client request. Idempotent — closing a session
    that is already terminal (or whose process died) returns its final record."""
    from audiagentic.components.agents import agents_gateway_session_bindings as binding_store
    from audiagentic.components.agents import agents_gateway_sessions_store as session_store
    from audiagentic.components.agents.agents_gateway_sessions import get_session_runtime

    runtime = get_session_runtime()
    if session_id in set(runtime.live_session_ids()):
        record = runtime.close_session(project_root, session_id, reason="client-request")
        return _public_session_projection(record)
    record = session_store.read_session_record(project_root, session_id)
    if record["state"] not in session_store.SESSION_TERMINAL_STATES:
        # Persisted active but not live here: orphaned by a restart.
        record = session_store.transition_session_record(
            project_root,
            session_id,
            "failed",
            updates={"close-reason": "orphaned"},
        )
        binding_store.retire_binding(project_root, record, state="failed")
    return _public_session_projection(record)


def resume_llm_session(
    project_root: Path,
    source_session_id: str,
    *,
    control_id: str,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """AS49: explicitly resume a terminal session as a new linked generation.

    Never triggered by ordinary continuation — this is the sole public entry
    point a client calls with the exact terminal ``source_session_id`` it
    wants to resume. ``control_id`` makes repeated calls idempotent (returns
    the original result, never creates a second successor generation).
    Raises a typed AudiaGenticError for every distinct rejection reason
    (source not terminal, capability unsupported/unvalidated, identity or
    execution context mismatch, provider rejection, persistence failure —
    see agents_gateway_session_resume.py) rather than silently opening a
    fresh conversation.
    """
    from audiagentic.components.agents.agents_gateway_sessions import get_session_runtime

    runtime = get_session_runtime()
    record = runtime.resume_session(
        project_root,
        source_session_id,
        control_id=control_id,
        identity_context_fingerprint=identity_context_fingerprint,
        execution_context_fingerprint=execution_context_fingerprint,
        model_id=model_id,
    )
    return _public_session_projection(record)


def gateway_overview(project_root: Path) -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state (works even
    after a process restart) plus in-process queue depths for active profiles.

    Answers "what's happening with the gateway right now" without already
    knowing a request-id (RV33/RV36/RV37 finding — status/README previously
    only exposed in-memory queue depths, which are empty after a restart even
    though persisted state still shows what happened).
    """
    records = store.list_records(project_root)
    by_state: dict[str, int] = {}
    for record in records:
        by_state[record["state"]] = by_state.get(record["state"], 0) + 1
    recent_failures = [
        {
            "request-id": r["request-id"],
            "agent-profile-id": r["agent-profile-id"],
            "error": r.get("error"),
        }
        for r in sorted(
            (r for r in records if r["state"] == "failed"),
            key=lambda r: r["updated-at"],
            reverse=True,
        )[:5]
    ]
    sessions = list_llm_sessions(project_root)
    return {
        "total_requests": len(records),
        "by_state": by_state,
        "recent_failures": recent_failures,
        "queues": _QUEUE_MANAGER.all_queue_depths(),
        "sessions": {
            "active-count": sum(1 for s in sessions if s["live"]),
            "sessions": [
                {
                    "session-id": s["session-id"],
                    "agent-profile-id": s["agent-profile-id"],
                    "provider-id": s.get("provider-id"),
                    "state": s["state"],
                    "live": s["live"],
                    "last-activity-at": s.get("last-activity-at"),
                    "turn-count": s.get("turn-count", 0),
                }
                for s in sessions[:10]
            ],
        },
        "runtime-fingerprint": _runtime_fingerprint(),
    }
