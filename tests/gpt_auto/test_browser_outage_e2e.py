"""Disposable CDP server through production bridge, transport, observer and queue."""

import asyncio
import json
import socket
import threading
from http import HTTPStatus

import pytest
from websockets.asyncio.server import serve

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue.queue import GatewayQueueManager
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.session import sessions as session_module
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.gateway.session.dispatch import _dispatch_session_request
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import PromptFingerprint
from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.components.providers.adapters.gpt_auto.turn import GptAutoTurn
from audiagentic.foundation.paths import home
from audiagentic.foundation.transports.agent_session import TransportObservationKind
from tests.unit.agents.test_agents_gateway_dispatch_sessions import (
    _RESUMABLE_PROFILE,
    _RESUMABLE_PROVIDER_ID,
    _RESUMABLE_SURFACE_ID,
    _register_resumable_descriptor,
)
from tests.unit.agents.test_agents_gateway_sessions import _build_fake_prepared

from .test_greenfield_config_urls import valid_config


@pytest.mark.asyncio
@pytest.mark.no_parallel
@pytest.mark.parametrize("remounted_final", [False, True])
@pytest.mark.parametrize("missing_prompt_id", [False, True])
@pytest.mark.parametrize("terminal_sink_fails", [False, True])
async def test_restart_offline_to_terminal_artifact_through_production_observer(monkeypatch, tmp_path, remounted_final, missing_prompt_id, terminal_sink_fails):
    original_emit = GptAutoTurn._emit

    async def emit(turn, kind, attributes):
        if terminal_sink_fails and kind is TransportObservationKind.TERMINAL:
            raise RuntimeError("injected terminal telemetry failure")
        await original_emit(turn, kind, attributes)

    monkeypatch.setattr(GptAutoTurn, "_emit", emit)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    settings = valid_config()
    settings["browser"]["dedicated-window"] = False
    settings["cdp"].update({"endpoint": f"http://127.0.0.1:{port}",
                            "connect-timeout-seconds": 0.1, "protocol-timeout-seconds": 1})
    settings["turn"].update({"response-stability-seconds": 0.01, "poll-interval-seconds": 0.01})
    config = GptAutoConfig.from_dict(settings)
    runtime = GptAutoProviderRuntime(config)
    monkeypatch.setattr(home, "global_provider_runtime", lambda *args, **kwargs: tmp_path / "provider")

    async def probe():
        # Exercise actual bounded CDP connect failures, without launching a browser.
        return True

    monkeypatch.setattr(runtime, "_cdp_available", probe)
    manager = GatewayQueueManager()
    first = store.build_record(execution_profile_id="profile-1", prompt_body="owned prompt",
        session_id="isolated-session", session_keep_alive=True, provider_transport_kind="provider-session",
        resolved_model_id="m1", gateway_profile_id="profile-1", gateway_profile_generation="generation-test",
        gateway_profile_config_digest="sha256:abcd1234", resolved_provider_id=_RESUMABLE_PROVIDER_ID,
        resolved_instance_ids=["m1"], gateway_profile_runtime={"surface-id": _RESUMABLE_SURFACE_ID,
            "provider-id": _RESUMABLE_PROVIDER_ID, "params": {"virtual-capacity": 1}})
    first.update({"state": "running", "worker-id": "recovery-worker", "attempt-epoch": 1,
                  "dispatch-owner-epoch": "replacement-owner", "recovery-required": True})
    first["watchdog-policy"] = {"policy-id": "test", "policy-digest": "test",
        "activity-lease-seconds": 300.0, "absolute-safety-ceiling-seconds": 0.0,
        "diagnostic-grace-seconds": 30.0, "initial-activity-grace-seconds": 1.0, "available": True}
    follower = store.build_record(execution_profile_id="profile-1", prompt_body="follower",
        session_id="isolated-session", session_keep_alive=True, provider_transport_kind="provider-session",
        resolved_model_id="m1")
    for record in (first, follower):
        store.write_record(tmp_path, record)
    url = "https://chatgpt.com/g/g-p-original/c/conversation"
    checkpoint = {"unresolved-turn-pending": True,
            "unresolved-turn-id": first["request-id"], "prompt-message-id": "u1",
            "submission-proven": True, "target-id": "old-target", "chat-url": url,
            "submission-proof-source": "provider-user-message",
            "prompt-text-digest": PromptFingerprint.from_text("owned prompt").digest,
            "submission-attempt-id": "prior-attempt", "submission-state": "proven",
            "send-intent-ever": True, "submission-stage": "send-click-acknowledged"}
    if missing_prompt_id:
        checkpoint.pop("prompt-message-id")
        checkpoint["unresolved-baseline-user-count"] = 0
        checkpoint["unresolved-baseline-assistant-count"] = 0
    first["provider-metadata"] = checkpoint.copy()
    store.write_record(tmp_path, first)
    sessions_store.write_session_record(tmp_path, sessions_store.build_session_record(
        session_id="isolated-session", created_by_request_id="prior-request",
        execution_profile_id="profile-1", provider_id=_RESUMABLE_PROVIDER_ID, model_id="m1",
        provider_session_ref="conversation", surface_id=_RESUMABLE_SURFACE_ID,
        provider_metadata=checkpoint,
    ))
    chats = []

    def prepare(project_root, **kwargs):
        chat = PersistentChat(ag_session_id=kwargs["ag_session_id"], project_name="original",
            project_url="https://chatgpt.com/g/g-p-original/project", runtime=runtime, config=config,
            binding_sink=kwargs["binding_sink"], checkpoint_sink=kwargs.get("checkpoint_sink"),
            provider_session_id=kwargs.get("resume_provider_ref"), chat_url=url,
            resume_provider_metadata=kwargs.get("resume_provider_metadata", checkpoint))
        chat.defer_unresolved_reconciliation()
        chats.append(chat)
        return _build_fake_prepared(GptAutoSessionTransport(chat),
            provider_id=_RESUMABLE_PROVIDER_ID, surface_id=_RESUMABLE_SURFACE_ID)

    import audiagentic.components.agents.configuration.global_catalog as agents_catalog
    from audiagentic.components.providers import providers_api

    _register_resumable_descriptor()
    sessions = SessionRuntime(provider_prepare_fn=prepare, reap_interval_seconds=60)
    monkeypatch.setattr(session_module, "get_session_runtime", lambda: sessions)
    monkeypatch.setattr(agents_catalog, "resolve_global_execution_profile", lambda *args: dict(_RESUMABLE_PROFILE))
    monkeypatch.setattr(providers_api, "get_provider_runtime_config_state", lambda *args: {
        "provider-id": _RESUMABLE_PROVIDER_ID, "enabled": True, "config": {}})
    methods, order = [], []
    target = {"targetId": "new-target", "type": "page", "url": url, "title": "isolated"}
    snapshot = {"url": url, "composerPresent": True, "composerEditable": True,
        "userCount": 1, "assistantCount": 1, "latestUserId": "u1", "userMessageIds": ["u1"],
        "latestUserText": "owned prompt", "latestAssistantId": "a1", "assistantMessageIds": ["a1"],
        "latestAssistantText": "completed during browser outage", "terminalWitnessAssistantId": "a1",
        "messageRefs": [{"role": "user", "messageId": "u1", "text": "owned prompt", "sequence": 0},
                        {"role": "assistant", "messageId": "a1", "text": "completed during browser outage", "sequence": 1}],
        "domSignals": {"completion-control": True, "more-actions-menu": True}, "generating": False}
    if remounted_final:
        snapshot["messageRefs"] = [
            {"role": "user", "messageId": "u1", "text": "owned prompt", "sequence": 0,
             "rendererTurnId": "turn-1", "rendererUnitId": "user-unit"},
            {"role": "assistant", "messageId": "fallback-assistant-1", "text": "intermediate",
             "sequence": 1, "rendererTurnId": "turn-1", "rendererUnitId": "assistant-unit"},
            {"role": "assistant", "messageId": "a1", "text": "completed during browser outage",
             "sequence": 2, "rendererTurnId": "turn-1", "rendererUnitId": "assistant-unit"},
        ]
        snapshot["assistantCount"] = 2
        snapshot["assistantMessageIds"] = ["fallback-assistant-1", "a1"]

    async def handler(connection):
        async for raw in connection:
            request = json.loads(raw)
            method = request["method"]
            methods.append(method)
            if method == "Target.getTargets":
                result = {"targetInfos": [target]}
            elif method == "Target.getTargetInfo":
                result = {"targetInfo": target}
            elif method == "Browser.getWindowForTarget":
                result = {"windowId": 1}
            elif method == "Target.attachToTarget":
                result = {"sessionId": "new-cdp-session"}
            elif method == "Runtime.evaluate":
                result = {"result": {"value": snapshot}}
            elif method in {"Target.setDiscoverTargets", "Page.enable", "Page.setLifecycleEventsEnabled"}:
                result = {}
            else:
                raise AssertionError(f"unexpected provider action during recovery: {method}")
            await connection.send(json.dumps({"id": request["id"], "result": result}))

    async def discovery(connection, request):
        if request.path == "/json/version":
            return connection.respond(HTTPStatus.OK, json.dumps({
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/new-generation",
            }))
        assert request.path == "/devtools/browser/new-generation"

    started = threading.Event()

    def runner(project, record, *, session_start=None):
        order.append(record["request-id"])
        if record["request-id"] == first["request-id"]:
            started.set()
            try:
                return _dispatch_session_request(project, record, dispatch_prompt="",
                    resume_existing=True, project_name="original", session_start=session_start)
            except RecoveryDeferred as exc:
                raise AssertionError(f"unexpected deferred finalization: {exc.error!r}") from exc
        else:
            if session_start is not None:
                record = session_start()
            output = "follower completed"
        return store.transition_record(project, record["request-id"], "completed", updates={"output": output})

    manager.enqueue_recovered_running(tmp_path, first, {"virtual-capacity": 1}, runner,
        dispatch_owner_epoch="replacement-owner", dispatch_service_root=tmp_path / "service")
    try:
        assert await asyncio.to_thread(started.wait, 1)
        manager.enqueue(tmp_path, follower, {"virtual-capacity": 1}, runner)
        await asyncio.sleep(0.4)  # Longer than a CDP connect attempt.
        assert store.read_record(tmp_path, first["request-id"])["state"] == "running"
        assert store.read_record(tmp_path, follower["request-id"])["state"] == "queued"
        async with serve(handler, "127.0.0.1", port, process_request=discovery):
            terminal = await asyncio.to_thread(manager.wait, tmp_path, first["request-id"], timeout_seconds=6)
            next_result = await asyncio.to_thread(manager.wait, tmp_path, follower["request-id"], timeout_seconds=2)
            assert terminal["state"] == next_result["state"] == "completed", terminal.get("error")
            assert terminal["output"] == "completed during browser outage"
            assert order == [first["request-id"], follower["request-id"]]
            assert chats[0].target_id == "new-target"
            assert not chats[0].unresolved_turn_pending, json.dumps({
                "private": chats[0]._terminal_checkpoint_finalization,
                "session": sessions_store.session_provider_metadata(sessions_store.read_session_record(tmp_path, terminal["session-id"])),
                "request": terminal.get("provider-metadata"),
            })
            assert terminal["response-artifact"]["artifact-id"] == "final-response"
            from audiagentic.components.agents.gateway.api import get_execution_response
            assert get_execution_response(tmp_path, first["request-id"]) == terminal["output"]
            cleared = sessions_store.read_session_record(tmp_path, terminal["session-id"])
            assert not sessions_store.session_provider_metadata(cleared).get("unresolved-turn-pending")
            assert not any(method.startswith("Input.") or method in {"Page.navigate", "Target.activateTarget", "Target.createTarget"} for method in methods)
            await asyncio.to_thread(sessions._call, runtime.shutdown(), 5)
    finally:
        manager.shutdown()
        if runtime.state != "stopped":
            await asyncio.to_thread(sessions._call, runtime.shutdown(), 5)
        await asyncio.to_thread(sessions.shutdown)
