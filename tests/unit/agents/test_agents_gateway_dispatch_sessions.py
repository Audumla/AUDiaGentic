"""AS04 — sessionful dispatch routing tests (plan agent-sessions).

Real SessionRuntime + fake transport; provider/profile seams monkeypatched.
Pins: keep-alive opens and completes, session-id continues on the SAME live
transport, unsupported provider is terminal UNS-AGW-001, profile mismatch is
terminal VAL-AGW-060, and the one-shot path is untouched for plain records.

AS28 slice 4a: injects PreparedSessionTransport via provider_prepare_fn —
no AcpLaunch/AcpSessionTransport in the open path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import dispatch as dispatch
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.session import dispatch as session_dispatch
from audiagentic.components.agents.gateway.session import sessions as sessions_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime

PROFILE = {
    "profile_id": "profile-1",
    "provider_id": "opencode",
    "instances": ["m1"],
    "model_alias": None,
    "surface_id": "test-surface",
    "params": {},
}

# GP13: the real "opencode" descriptor used by PROFILE above does not
# declare RESUME_BY_REF support, so auto-resume tests need their own
# resumable descriptor -- same pattern as
# test_agents_gateway_sessions_resume_dispatch.py's _register_resumable_descriptor.
# Surface id is pinned to "opencode-acp" because _build_fake_prepared (this
# rig's fake provider_prepare_fn helper, shared with test_agents_gateway_
# sessions.py) always echoes that exact surface id back regardless of the
# SurfaceHint it was given -- only the provider id actually reflects what
# was requested, so the registered descriptor's surface id must match the
# fake's hardcoded echo for resolve_session_surface to find it.
_RESUMABLE_PROVIDER_ID = "test-gp13-resumable-provider"
_RESUMABLE_SURFACE_ID = "opencode-acp"
_RESUMABLE_PROFILE = dict(PROFILE, provider_id=_RESUMABLE_PROVIDER_ID, surface_id=_RESUMABLE_SURFACE_ID)


def _register_resumable_descriptor() -> None:
    from audiagentic.components.providers.descriptors.base import ProviderDescriptor
    from audiagentic.components.providers.descriptors.registry import register
    from audiagentic.components.providers.descriptors.session_surface_declarations import (
        SessionSurfaceDeclaration,
    )
    from audiagentic.foundation.transports.session_surface import (
        ControlSupport,
        SessionIdentityOperation,
        SessionMappingFacts,
        ValidationEvidence,
    )

    decl = SessionSurfaceDeclaration(
        surface_id=_RESUMABLE_SURFACE_ID,
        version_constraint=">=1.0",
        identity_operations={
            SessionIdentityOperation.OPEN: ControlSupport.SUPPORTED,
            SessionIdentityOperation.RESUME_BY_REF: ControlSupport.SUPPORTED,
        },
        mapping_facts=SessionMappingFacts(ref_namespace="provider-session-ref"),
        evidence=ValidationEvidence(validated=True, reference="test"),
    )
    register(
        ProviderDescriptor(
            provider_id=_RESUMABLE_PROVIDER_ID,
            display_name=_RESUMABLE_PROVIDER_ID,
            execution_isolation_tier="no-isolation",
            session_surfaces=(decl,),
        )
    )


@pytest.fixture
def resumable_rig(rig, monkeypatch):
    """GP13 auto-resume tests: same rig, but resolved against a provider
    whose registered descriptor actually declares resume-by-ref support."""
    import audiagentic.components.agents.configuration.global_catalog as agents_catalog
    from audiagentic.components.providers.descriptors.registry import _registry
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )

    runtime, transports, tmp_path = rig
    _registry._items.clear()
    _register_resumable_descriptor()
    set_provider_enabled(tmp_path, _RESUMABLE_PROVIDER_ID, enabled=True)
    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: dict(_RESUMABLE_PROFILE))
    yield runtime, transports, tmp_path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = _Clock()
    transports: list[FakeAgentSessionTransport] = []

    def fake_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = FakeAgentSessionTransport()
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(
        clock=clock,
        reap_interval_seconds=60,
        provider_prepare_fn=fake_prepare,
    )
    monkeypatch.setattr(sessions_module, "get_session_runtime", lambda: runtime)

    import audiagentic.components.agents.configuration.global_catalog as agents_catalog

    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: dict(PROFILE))
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.get_provider_runtime_config_state",
        lambda root, provider_id: {
            "provider-id": provider_id,
            "enabled": True,
            "config": {},
        },
    )
    yield runtime, transports, tmp_path
    runtime.shutdown()


def _running_record(tmp_path, **kwargs):
    # AS105/AS101: dispatch.py reads the bound model from resolved-model-id,
    # normally injected by queue.py's _run_one at dispatch time. Tests here
    # call dispatch.dispatch_request directly, bypassing the queue.
    admit_session = kwargs.pop("admit_session", True)
    kwargs.setdefault("resolved_model_id", "m1")
    provider_session = bool(
        kwargs.get("provider_transport_kind") == "provider-session"
        or kwargs.get("session_keep_alive")
        or kwargs.get("session_id")
    )
    create_admitted_session = False
    if provider_session:
        session_id = kwargs.setdefault("session_id", sessions_store.generate_session_id())
        kwargs.setdefault("provider_transport_kind", "provider-session")
        try:
            sessions_store.read_session_record(tmp_path, session_id)
        except Exception:  # a test fixture is creating this admitted session
            create_admitted_session = admit_session
    else:
        kwargs.setdefault("provider_transport_kind", "worker")
    record = store.build_record(execution_profile_id="profile-1", prompt_body="hello", **kwargs)
    if create_admitted_session:
        sessions_store.write_session_record(
            tmp_path,
            sessions_store.build_session_record(
                session_id=session_id,
                created_by_request_id=record["request-id"],
                provider_transport_kind="provider-session",
                execution_profile_id="profile-1",
                provider_id="opencode",
                model_id="m1",
            ),
        )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    return store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-test",
        worker_id="worker_test",
        expected_revision=claimed["revision"],
    )


def _dispatch(
    tmp_path,
    record,
    *,
    dispatch_prompt,
    preallocated_session_id=None,
    provider_isolation_tier="full-isolation",
    context_fingerprint="0" * 64,
    resume_existing=False,
):
    return dispatch.dispatch_request(
        tmp_path,
        record,
        dispatch_prompt=dispatch_prompt,
        preallocated_session_id=preallocated_session_id,
        manifest_id="mf_test",
        context_fingerprint=context_fingerprint,
        component_profile="",
        provider_isolation_tier=provider_isolation_tier,
        worker_timeout_seconds=10,
        resume_existing=resume_existing,
    )


def test_keep_alive_opens_session_and_completes(rig):
    runtime, transports, tmp_path = rig
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="do the thing")
    assert result["state"] == "completed"
    assert result["session-id"] is not None
    assert result["provider-id"] == "opencode"
    assert result["completion"]["binding"]["provider-ref-key-prefix"]
    assert "provider-session-ref" not in repr(result["completion"])
    assert len(transports) == 1
    # SH02 keeps prompt bodies out of persisted records; dispatch receives the
    # raw prompt through its in-memory argument instead.
    assert transports[0].turns == ["do the thing"]
    assert not transports[0].closed  # keep-alive: session survives the request
    request_dir = (
        tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / record["request-id"]
    )
    assert (request_dir / "runtime").is_dir()


@pytest.mark.parametrize("ambiguous,always_fail,expected_calls", [(False,False,2),(False,True,2),(True,True,1)])
def test_composer_retry_preserves_session_and_is_bounded(rig, monkeypatch, ambiguous, always_fail, expected_calls):
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    session_id = first["session-id"]
    original = runtime.prompt_in_session
    calls = []
    def prompt(*args, **kwargs):
        calls.append(args[1])
        if always_fail or len(calls) == 1:
            raise AudiaGenticError(code="EXT-GPTAUTO-004", kind="providers", message="composer timeout", details={
                "failure-stage": "readiness", "submission-state": "not_started",
                "submission-proven": False, "submission-ambiguous": ambiguous,
                "retryable-same-session": not ambiguous,
            })
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=session_id, session_keep_alive=True)
    result = _dispatch(root, record, dispatch_prompt="followup")
    assert calls == [session_id] * expected_calls
    assert result["session-id"] == session_id
    assert result["state"] == ("failed" if always_fail else "completed")
    assert len(transports) == 1


def test_generic_provider_error_defers_without_automatic_resubmit(rig, monkeypatch):
    """An ambiguous provider alert never causes a second automatic prompt."""
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    session_id = first["session-id"]
    prompts: list[str] = []

    def prompt(*args, **kwargs):
        prompts.append(args[2])
        raise AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="provider failure policy matched: request-error-alert",
            details={
                "failure-reason": "provider-failure-policy-matched",
                "evidence": ["request-error-alert"],
                "dom-signals": ["error-alert"],
                "failure-response-available": False,
            },
        )

    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred):
        _dispatch(root, record, dispatch_prompt="first")

    assert prompts == ["first"]
    assert len(transports) == 1


def test_conversation_load_failure_after_submission_never_replays_in_fresh_session(rig, monkeypatch):
    """A submitted turn must not be duplicated just because its page reloads."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    session_id = first["session-id"]
    prompts: list[tuple[str, str]] = []

    def prompt(*args, **kwargs):
        prompts.append((args[1], args[2]))
        if len(prompts) == 1:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="provider failure policy matched: conversation-load-failed",
                details={
                    "failure-reason": "conversation-load-failed",
                    "dom-signals": ["conversation-load-failed"],
                    "submission-proven": True,
                    "submission-attempted": True,
                    "failure-response-available": False,
                },
            )
        raise AssertionError("submitted conversation was replayed")

    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as deferred:
        _dispatch(root, record, dispatch_prompt="first")

    assert deferred.value.phase == "conversation-load-reconcile"
    stored = store.read_record(root, record["request-id"])
    assert stored["state"] == "running"
    assert stored["session-id"] == session_id
    assert prompts == [(session_id, "first")]
    assert len(transports) == 1


def test_proven_unsent_conversation_load_failure_retries_in_new_session(rig, monkeypatch):
    """A load failure before Send may safely move this request to a new session."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    original = runtime.prompt_in_session
    original_prepare = runtime._provider_prepare_fn
    calls: list[str] = []

    def prepare(*args, **kwargs):
        prepared = original_prepare(*args, **kwargs)
        prepared.transport.provider_session_ref = "prov-ses-replacement"
        return prepared

    runtime._provider_prepare_fn = prepare

    def prompt(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 1:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-005",
                kind="providers",
                message="conversation could not be loaded after bounded recovery",
                details={
                    "failure-reason": "conversation-load-failed",
                    "submission-proven": False,
                    "submission-attempted": False,
                    "submission-ambiguous": False,
                    "failure-stage": "readiness",
                    "submission-state": "not_started",
                    "dom-signals": ["conversation-load-failed"],
                },
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=first["session-id"], session_keep_alive=True)
    result = _dispatch(root, record, dispatch_prompt="retry-me")

    assert result["state"] == "completed", result
    assert calls[0] == first["session-id"]
    assert calls[1] != calls[0]
    assert result["session-id"] == calls[1]
    assert len(transports) == 2
    assert transports[1].turns == ["retry-me"]


def test_conversation_load_failure_without_unsent_proof_never_replays(rig, monkeypatch):
    """An incomplete failure payload must fail closed instead of replaying."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    session_id = first["session-id"]
    prompts: list[tuple[str, str]] = []

    def prompt(*args, **kwargs):
        prompts.append((args[1], args[2]))
        if len(prompts) == 1:
            raise AudiaGenticError(
                code="EXT-GPTAUTO-003",
                kind="providers",
                message="provider failure policy matched: conversation-load-failed",
                details={
                    "failure-reason": "conversation-load-failed",
                    "dom-signals": ["conversation-load-failed"],
                    "submission-proven": False,
                    "submission-attempted": True,
                },
            )
        raise AssertionError("conversation-load failure without unsent proof was replayed")

    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as deferred:
        _dispatch(root, record, dispatch_prompt="first")

    assert deferred.value.phase == "conversation-load-reconcile"
    stored = store.read_record(root, record["request-id"])
    assert stored["state"] == "running"
    assert stored["session-id"] == session_id
    assert prompts == [(session_id, "first")]
    assert len(transports) == 1


def test_failed_followup_defers_observation_and_keeps_request_running(rig, monkeypatch):
    """A recovery prompt may be generating after its provider alert fires."""
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, root = rig
    first = _dispatch(root, _running_record(root, session_keep_alive=True), dispatch_prompt="first")
    session_id = first["session-id"]
    prompts: list[str] = []

    def prompt(*args, **kwargs):
        prompts.append(args[2])
        raise AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="provider failure policy matched: network-error-alert",
            details={
                "failure-reason": "provider-failure-policy-matched",
                "evidence": ["error-alert", "network-error-alert"],
                "dom-signals": ["error-alert", "network-error-alert"],
                "failure-response-available": True,
                "failure-response-text": "partial review",
            },
        )

    monkeypatch.setattr(runtime, "prompt_in_session", prompt)
    record = _running_record(root, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(root, record, dispatch_prompt="first")

    assert exc.value.phase == "followup-reconcile"
    assert exc.value.side_effect_state == "may-have-started"
    assert len(prompts) == 1
    stored = store.read_record(root, record["request-id"])
    assert stored["state"] == "running"
    assert stored["failure-response-preview"] == "partial review"
    assert stored["failure-response-truncated"] is False
    assert stored["failure-response-artifact"]["artifact-id"] == "failure-response"
    assert len(transports) == 1


def test_profile_turn_deadline_never_cancels_a_session_turn(rig, monkeypatch):
    """A profile's legacy elapsed-time setting cannot override activity policy."""
    runtime, _transports, tmp_path = rig
    seen: dict[str, object] = {}
    original = runtime.prompt_in_session

    def capture_timeout(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout_seconds")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "prompt_in_session", capture_timeout)
    import audiagentic.components.agents.configuration.global_catalog as agents_catalog

    profile = dict(PROFILE, params={"session-turn-timeout-seconds": 0.001})
    monkeypatch.setattr(
        agents_catalog, "resolve_global_execution_profile", lambda root, pid: dict(profile)
    )
    record = _running_record(tmp_path, session_keep_alive=True)

    result = _dispatch(tmp_path, record, dispatch_prompt="respond")

    assert result["state"] == "completed"
    assert seen["timeout"] is None


def test_preallocated_session_id_opens_new_session(rig):
    runtime, transports, tmp_path = rig
    preallocated = "ses_preallocated"
    record = _running_record(tmp_path, session_id=preallocated, session_keep_alive=True)
    result = _dispatch(
        tmp_path,
        record,
        dispatch_prompt="hello",
        preallocated_session_id=preallocated,
    )
    assert result["state"] == "completed"
    assert result["session-id"] == preallocated
    assert len(transports) == 1


def test_session_id_continues_same_live_transport(rig):
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="hello"
    )
    assert second["state"] == "completed"
    assert second["session-id"] == session_id
    assert len(transports) == 1  # no second child spawned
    assert transports[0].turns == ["hello", "hello"]


def test_stale_active_rehydrate_failure_is_deferred_for_retry(rig, monkeypatch):
    """A post-restart rehydrate failure cannot terminally reject the turn."""
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, _transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    monkeypatch.setattr(runtime, "session_runtime_status", lambda _session_id: {"available": False})

    def rehydrate_failure(*_args, **_kwargs):
        raise AudiaGenticError(
            code="EXT-AGW-118",
            kind="agents",
            message="provider rejected durable session rehydration",
        )

    monkeypatch.setattr(runtime, "rehydrate_session", rehydrate_failure)
    record = _running_record(tmp_path, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(
            tmp_path,
            record,
            dispatch_prompt="after restart",
            resume_existing=True,
        )

    assert exc.value.phase == "rehydrate-retry"
    assert exc.value.side_effect_state == "may-have-started"

def test_promptless_restart_resume_reaches_provider_observer(rig, monkeypatch):
    """A recovered running turn must not fail before observation-only resume."""
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_keep_alive=True),
        dispatch_prompt="hello",
    )
    session_id = first["session-id"]
    record = _running_record(
        tmp_path,
        session_id=session_id,
        session_keep_alive=True,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.complete_execution_from_provider",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(RecoveryDeferred, match="cannot recover an existing turn"):
        _dispatch(
            tmp_path,
            record,
            dispatch_prompt="",
            resume_existing=True,
        )

    # The fake transport has no existing-turn implementation, but the call
    # reached that provider seam. It did not fail at the prompt-availability
    # guard or replay the original prompt.
    assert len(transports) == 1
    assert transports[0].turns == ["hello"]


@pytest.mark.parametrize("close_reason", ["shutdown", "idle-timeout"])
def test_promptless_restart_recovery_reopens_policy_closed_session(
    resumable_rig, monkeypatch, close_reason
):
    """Restart recovery (resume_existing=True, no prompt to replay) against a
    session closed by a resumable gateway resource-policy reason must reopen
    the exact durable provider binding through the shared auto-resume path
    and reach the provider's observation-only seam — instead of looping on
    RES-AGW-003 until the bounded CON-AGW-084 interruption."""
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    source_id = first["session-id"]
    runtime.close_session(tmp_path, source_id, reason=close_reason)

    # Simulate the restart: the prompt snapshot is gone, so recovery enters
    # dispatch promptless with observation-only semantics.
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.complete_execution_from_provider",
        lambda *_args, **_kwargs: None,
    )
    seen: dict[str, object] = {}
    original_prompt = runtime.prompt_in_session

    def capture_prompt(*args, **kwargs):
        seen["prompt"] = args[2]
        seen["resume-existing"] = kwargs.get("resume_existing")
        return original_prompt(*args, **kwargs)

    monkeypatch.setattr(runtime, "prompt_in_session", capture_prompt)

    record = _running_record(tmp_path, session_id=source_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(tmp_path, record, dispatch_prompt="", resume_existing=True)

    # The closed source was transparently resumed; the deferred error is the
    # provider seam's observation refusal, NOT RES-AGW-003.
    assert exc.value.error.code == "CON-AGW-124", exc.value.error
    assert exc.value.phase == "observe-retry"
    # The successor transport was opened and observed prompt-free: no second
    # prompt was submitted to any transport.
    assert len(transports) == 2
    assert transports[0].turns == ["hello"]
    assert transports[1].turns == []
    assert seen["prompt"] == ""
    assert seen["resume-existing"] is True

    stored = store.read_record(tmp_path, record["request-id"])
    assert stored["state"] == "running"
    successor_id = stored["session-id"]
    assert successor_id != source_id
    successor = sessions_store.read_session_record(tmp_path, successor_id)
    assert successor["binding"]["relation"] == "resumed-from"


@pytest.mark.parametrize("close_reason", ["client-request", "post-turn-close"])
def test_promptless_restart_recovery_refuses_ineligible_close_reason(
    resumable_rig, monkeypatch, close_reason
):
    """A client-request or post-turn close is deliberate, not a resource
    policy: promptless restart recovery must still surface the existing
    RES-AGW-003 refusal (deferred for the queue) and must never reopen the
    session."""
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    source_id = first["session-id"]
    runtime.close_session(tmp_path, source_id, reason=close_reason)
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.complete_execution_from_provider",
        lambda *_args, **_kwargs: None,
    )
    record = _running_record(tmp_path, session_id=source_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(tmp_path, record, dispatch_prompt="", resume_existing=True)

    assert exc.value.error.code == "RES-AGW-003", exc.value.error
    assert exc.value.phase == "rehydrate-retry"
    assert len(transports) == 1  # no successor transport was ever opened
    stored = store.read_record(tmp_path, record["request-id"])
    assert stored["session-id"] == source_id
    assert stored["state"] == "running"


def test_promptless_restart_recovery_refuses_source_without_durable_binding(
    resumable_rig, monkeypatch
):
    """AS49 eligibility refusal (no usable provider binding) is fail-closed:
    the source is never reopened and the caller sees the stable RES-AGW-003.
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    source_id = first["session-id"]
    runtime.close_session(tmp_path, source_id, reason="shutdown")

    def refuse(*args, **kwargs):
        raise AudiaGenticError(
            code="RES-AGW-111",
            kind="agents",
            message="source session has no usable provider binding",
            details={},
        )

    monkeypatch.setattr(runtime, "resume_session", refuse)
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.complete_execution_from_provider",
        lambda *_args, **_kwargs: None,
    )
    record = _running_record(tmp_path, session_id=source_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(tmp_path, record, dispatch_prompt="", resume_existing=True)

    assert exc.value.error.code == "RES-AGW-003", exc.value.error
    assert exc.value.error.details.get("auto-resume-attempted") is True
    assert exc.value.error.details.get("auto-resume-refusal-code") == "RES-AGW-111"
    assert len(transports) == 1
    stored = store.read_record(tmp_path, record["request-id"])
    assert stored["session-id"] == source_id


def test_proven_unsent_submission_failure_is_deferred_after_safe_retry(rig, monkeypatch):
    """A composer failure before Send stays queued, never rotates the session."""
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, _transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    calls = []

    def proven_unsent_failure(*_args, **_kwargs):
        calls.append(session_id)
        raise AudiaGenticError(
            code="EXT-GPTAUTO-003",
            kind="providers",
            message="composer unavailable before Send",
            details={
                "failure-stage": "submission",
                "submission-state": "not_started",
                "submission-proven": False,
                "submission-ambiguous": False,
                "retryable-same-session": True,
            },
        )

    monkeypatch.setattr(runtime, "prompt_in_session", proven_unsent_failure)
    record = _running_record(tmp_path, session_id=session_id, session_keep_alive=True)
    with pytest.raises(RecoveryDeferred) as exc:
        _dispatch(tmp_path, record, dispatch_prompt="after restart")

    assert calls == [session_id, session_id]
    assert exc.value.phase == "presubmit-retry"
    assert exc.value.side_effect_state == "not-started"
    stored = store.read_record(tmp_path, record["request-id"])
    assert stored["state"] == "running"
    assert stored["session-id"] == session_id


def test_persistent_surface_ignores_execution_context_drift_on_continuation(
    rig, monkeypatch
):
    """Persistent provider conversations survive a gateway context change.

    The request manifest fingerprint changes across a gateway restart/config
    reload.  A surface that explicitly declares
    ``requires_same_execution_context=False`` must continue its durable
    provider conversation; strict surfaces keep the exact-match guard.
    """
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_keep_alive=True),
        dispatch_prompt="hello",
        context_fingerprint="0" * 64,
    )
    session_id = first["session-id"]

    from audiagentic.foundation.transports.session_surface import SessionMappingFacts

    surface = SimpleNamespace(
        identity=SimpleNamespace(
            mapping_facts=SessionMappingFacts(
                requires_same_execution_context=False,
            )
        )
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.resolve_session_surface",
        lambda *args, **kwargs: surface,
    )

    second = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_id=session_id),
        dispatch_prompt="after restart",
        context_fingerprint="1" * 64,
    )
    assert second["state"] == "completed", second
    assert second["session-id"] == session_id
    assert transports[0].turns == ["hello", "after restart"]


def test_unsupported_provider_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    # AS28 slice 4a: unsupported surface path — provider_prepare_fn returns
    # PreparedSessionTransport with transport=None, which raises CON-AGW-095.
    def unsupported_prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):

        return _build_fake_prepared(None)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime, "_provider_prepare_fn", unsupported_prepare)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="hello")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "CON-AGW-095"
    assert transports == []
    request_dir = (
        tmp_path / ".audiagentic" / "runtime" / "agent-execution-gateway" / record["request-id"]
    )
    assert (request_dir / "quarantine" / record["request-id"]).is_dir()


def test_profile_mismatch_terminal(rig, monkeypatch):
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]

    import audiagentic.components.agents.configuration.global_catalog as agents_catalog

    other = dict(PROFILE, profile_id="profile-2")
    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda root, pid: other)
    record = store.build_record(
        execution_profile_id="profile-2",
        prompt_body="hi",
        session_id=session_id,
        provider_transport_kind="provider-session",
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-test",
        worker_id="worker_test_mismatch",
        expected_revision=claimed["revision"],
    )
    result = _dispatch(tmp_path, running, dispatch_prompt="hi")
    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-060"
    assert transports[0].turns == ["hello"]  # mismatch never reached the agent


def test_unknown_session_terminal(rig):
    runtime, transports, tmp_path = rig
    result = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_id="ses_nope", admit_session=False),
        dispatch_prompt="hi",
    )
    assert result["state"] == "failed"
    assert result["error"]["code"] == "RES-AGW-002"


def test_session_output_concatenates_stream_chunks():
    """AS28: final_summary carries bounded assistant-text fragments."""
    from types import SimpleNamespace

    # SessionTurnResult with final_summary containing concatenated text fragments
    result = SimpleNamespace(
        final_summary="TOKEN STORED.",
    )
    assert session_dispatch._session_output_from_result(result) == "TOKEN STORED."


def test_completed_session_without_assistant_text_fails_without_fake_artifact(rig, monkeypatch):
    """A transport acknowledgement is not a successful agent response.

    Regression for Pi ACP turns that previously persisted literal ``None`` as
    a completed response artifact.
    """
    from audiagentic.foundation.transports.agent_session import SessionTurnResult

    runtime, _transports, tmp_path = rig

    def no_summary(*_args, **kwargs):
        return SessionTurnResult(
            turn_id=kwargs["request_id"],
            stop_reason="end_turn",
            observations_delivered=0,
            dropped_observations=0,
        )

    monkeypatch.setattr(runtime, "prompt_in_session", no_summary)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="reply")

    assert result["state"] == "failed"
    assert result["error"]["code"] == "EXT-AGW-119"
    assert result.get("response-artifact") is None
    assert result.get("output-preview") is None


def test_stale_session_runtime_failure_explains_prompt_was_not_submitted(rig, monkeypatch):
    """A process-local handle miss is actionable, not an opaque RES-AGW-003."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, _transports, tmp_path = rig

    def stale_prompt(*_args, **_kwargs):
        raise AudiaGenticError(
            code="RES-AGW-003",
            kind="agents",
            message="session is not active in this gateway process",
            details={"session-id": "stale"},
        )

    monkeypatch.setattr(runtime, "prompt_in_session", stale_prompt)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="reply")

    assert result["state"] == "failed"
    assert result["error"]["code"] == "RES-AGW-003"
    assert "durable provider session is not attached" in result["error"]["message"]
    stored_error = store.read_record(tmp_path, record["request-id"])["error"]
    assert stored_error["details"]["failure-reason"] == "stale-session-runtime"
    assert stored_error["details"]["prompt-submission"] == "not-started"
    assert stored_error["details"]["recovery-action"] == (
        "retry-continuation-to-rehydrate-session"
    )


def test_provider_cancelled_turn_preserves_output_and_error_artifact(rig, monkeypatch):
    """A provider-side cancellation is a failure with retrievable output.

    Codex can return ``stop_reason=cancelled`` after one of its own tool
    calls fails.  That is distinct from an explicit gateway cancellation and
    must not discard the assistant text emitted before the failed tool.
    """
    from audiagentic.foundation.transports.agent_session import SessionTurnResult

    runtime, _transports, tmp_path = rig

    def provider_cancelled(*_args, **kwargs):
        return SessionTurnResult(
            turn_id=kwargs["request_id"],
            stop_reason="cancelled",
            observations_delivered=3,
            dropped_observations=0,
            error_code="EXT-ACP-TOOL-001",
            final_summary="I completed the local checks before the remote tool failed.",
            metadata={
                "cancelled-by-signal": False,
                "failed-tool-call-count": 1,
                "failed-tool-call-ids": ("tool-1",),
            },
        )

    monkeypatch.setattr(runtime, "prompt_in_session", provider_cancelled)
    record = _running_record(tmp_path, session_keep_alive=True)
    result = _dispatch(tmp_path, record, dispatch_prompt="review")

    assert result["state"] == "failed"
    assert result["error"]["code"] == "EXT-ACP-TOOL-001"
    assert result["error"]["details"]["reason-code"] == "provider-cancelled-after-tool-failure"
    assert result["error"]["details"]["failed-tool-call-count"] == 1
    assert result["error"]["details"]["assistant-output-available"] is True
    assert result["output"] == "I completed the local checks before the remote tool failed."
    assert result["response-artifact"]["artifact-id"] == "final-response"
    assert result["output-truncated"] is False

    from audiagentic.components.agents.gateway.api import get_execution_response

    assert get_execution_response(tmp_path, record["request-id"]) == result["output"]


def test_explicit_cancelled_turn_remains_cancelled(rig, monkeypatch):
    """A caller-requested cancellation keeps cancellation semantics."""
    from audiagentic.foundation.transports.agent_session import SessionTurnResult

    runtime, _transports, tmp_path = rig

    def caller_cancelled(*_args, **kwargs):
        return SessionTurnResult(
            turn_id=kwargs["request_id"],
            stop_reason="cancelled",
            observations_delivered=0,
            dropped_observations=0,
            metadata={"cancelled-by-signal": True},
        )

    monkeypatch.setattr(runtime, "prompt_in_session", caller_cancelled)
    record = _running_record(tmp_path, session_keep_alive=True)
    record = store.mark_cancel_requested(tmp_path, record["request-id"])
    result = _dispatch(tmp_path, record, dispatch_prompt="cancel")

    assert result["state"] == "cancelled"
    assert result.get("error") is None


def test_plain_record_does_not_touch_session_path(rig, monkeypatch):
    runtime, transports, tmp_path = rig

    def boom(*args, **kwargs):  # session runtime must not be consulted
        raise AssertionError("session path used for a plain record")

    monkeypatch.setattr(sessions_module, "get_session_runtime", boom)

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        lambda **kwargs: SimpleNamespace(
            result_data={"provider-id": "opencode", "model": "m1", "output": "ok"}
        ),
    )
    result = _dispatch(tmp_path, _running_record(tmp_path), dispatch_prompt="do the thing")
    assert result["state"] == "completed", result
    assert transports == []


def test_closed_by_shutdown_session_transparently_resumes(resumable_rig):
    """GP13 (scoped): a session closed specifically by a gateway shutdown
    (the exact shape a force gateway_restart() produces machine-wide) is
    transparently reattached on the next continuation instead of forcing
    RES-AGW-003 -- reproduced live 2026-08-17 when a force restart
    (loading unrelated fixes) collaterally closed a concurrent agent's
    session in a different project."""
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "completed", second
    # AS49/AS30: resume always creates a new generation -- never aliases the
    # closed source id onto the successor.
    assert second["session-id"] != session_id
    assert len(transports) == 2
    assert transports[1].turns == ["are you there"]

    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    successor = session_store.read_session_record(tmp_path, second["session-id"])
    assert successor["binding"]["relation"] == "resumed-from"
    assert successor["binding"]["predecessor-binding-id"] is not None


def test_idle_closed_session_transparently_resumes(resumable_rig):
    """An idle reaper releases the live harness resource, but the durable
    provider conversation remains eligible for the next session turn."""
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path,
        _running_record(tmp_path, session_keep_alive=True),
        dispatch_prompt="hello",
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="idle-timeout")

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="continue"
    )

    assert second["state"] == "completed", second
    assert second["session-id"] != session_id
    assert transports[1].turns == ["continue"]
    successor = sessions_store.read_session_record(tmp_path, second["session-id"])
    assert successor["binding"]["relation"] == "resumed-from"


def test_auto_resume_skips_terminal_idempotent_successor(resumable_rig, monkeypatch):
    """A shutdown can close the idempotent successor before its first use.

    The next continuation must advance one bounded generation instead of
    returning that same terminal successor forever.
    """
    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    source_id = first["session-id"]
    runtime.close_session(tmp_path, source_id, reason="shutdown")
    original_resume = runtime.resume_session
    calls = []

    def resume_then_shutdown(*args, **kwargs):
        result = original_resume(*args, **kwargs)
        calls.append(result["session-id"])
        if len(calls) == 1:
            runtime.close_session(tmp_path, result["session-id"], reason="shutdown")
        return result

    monkeypatch.setattr(runtime, "resume_session", resume_then_shutdown)
    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=source_id), dispatch_prompt="continue"
    )
    assert second["state"] == "completed", second
    assert len(calls) == 2
    assert second["session-id"] == calls[-1]
    assert second["session-id"] != calls[0]


def test_closed_by_non_shutdown_reason_still_raises_res_agw_003(rig):
    """A session closed for any reason OTHER than a gateway shutdown (client
    request, post-turn auto-close, etc.) must NOT be transparently resumed
    -- GP13's own notes are explicit that undoing an intentional close is
    much closer to a correctness bug than the restart problem being fixed."""
    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="client-request")

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"
    assert len(transports) == 1  # no successor transport was ever opened


def test_failed_session_never_auto_resumes(rig):
    """A genuinely failed session must still require the caller's own
    explicit session_resume -- GP13's core invariant: a real terminal
    failure is never silently papered over by a transparent resume."""
    from audiagentic.components.agents.gateway.session import sessions_store as session_store

    runtime, transports, tmp_path = rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    session_store.transition_session_record(
        tmp_path, session_id, "failed", updates={"close-reason": "failed"}
    )
    # transition_session_record only touches the durable record -- the
    # runtime's own live in-process handle registry is a separate thing
    # entirely (a real "failed" session usually loses its handle via the
    # same event that fails it). Drop it directly so
    # session_runtime_status(...).get("available") is False, exactly like
    # after a real crash/restart.
    runtime._handles.pop(session_id, None)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"
    assert len(transports) == 1


def test_auto_resume_expected_refusal_falls_back_to_res_agw_003(resumable_rig, monkeypatch):
    """An expected AS49 eligibility refusal (e.g. the resolved surface
    doesn't actually support resume-by-ref) must fall back to the ordinary
    RES-AGW-003 the caller already knows how to handle -- resume is a
    best-effort transparent upgrade, never a new, different failure mode."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    def refuse(*args, **kwargs):
        raise AudiaGenticError(
            code="UNS-AGW-112",
            kind="agents",
            message="resolved session surface does not support resume-by-ref",
            details={},
        )

    monkeypatch.setattr(runtime, "resume_session", refuse)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "RES-AGW-003"


def test_auto_resume_unexpected_error_propagates_as_itself(resumable_rig, monkeypatch):
    """An error OUTSIDE AS49's known eligibility-refusal taxonomy (a store
    failure, a lost ownership fence, an internal resume defect) must never
    be masked as mere ineligibility -- it has to surface as itself so a
    real bug is never hidden behind an innocuous 'session isn't active'.
    CON-AGW-002 ("session runtime has been shut down") is a real,
    registered error code that is deliberately NOT in
    _AUTO_RESUME_EXPECTED_REFUSAL_CODES -- it stands in for any internal
    resume failure outside AS49's own eligibility taxonomy."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    runtime, transports, tmp_path = resumable_rig
    first = _dispatch(
        tmp_path, _running_record(tmp_path, session_keep_alive=True), dispatch_prompt="hello"
    )
    session_id = first["session-id"]
    runtime.close_session(tmp_path, session_id, reason="shutdown")

    def explode(*args, **kwargs):
        raise AudiaGenticError(
            code="CON-AGW-002",
            kind="agents",
            message="session runtime has been shut down",
            details={},
        )

    monkeypatch.setattr(runtime, "resume_session", explode)

    second = _dispatch(
        tmp_path, _running_record(tmp_path, session_id=session_id), dispatch_prompt="are you there"
    )
    assert second["state"] == "failed"
    assert second["error"]["code"] == "CON-AGW-002"


def test_no_isolation_plain_record_routes_through_ephemeral_session(rig, monkeypatch):
    """SH23: a no-isolation provider has no disposable-subprocess-per-attempt
    story (e.g. gpt-auto is CDP-attached to one already-running browser), so a
    plain one-shot submit — no session_id, no session_keep_alive — must not
    reach worker_host at all. It should open a session, run exactly one turn,
    and auto-close it, exactly like a keep-alive=false continued session does.
    """
    runtime, transports, tmp_path = rig

    def boom(**kwargs):  # worker_host must not be consulted for no-isolation
        raise AssertionError("worker path used for a no-isolation provider")

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        boom,
    )

    result = _dispatch(
        tmp_path,
        _running_record(tmp_path, provider_transport_kind="provider-session"),
        dispatch_prompt="do the thing",
        provider_isolation_tier="no-isolation",
    )
    assert result["state"] == "completed", result
    assert result["session-id"] is not None
    assert len(transports) == 1
    assert transports[0].turns == ["do the thing"]
    assert transports[0].closed  # not keep-alive: ephemeral session auto-closes
