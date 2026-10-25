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
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    GptAutoSessionTransport,
)
from audiagentic.foundation.paths import home
from audiagentic.foundation.transports.agent_session import SessionPrompt

from .test_greenfield_config_urls import valid_config


@pytest.mark.asyncio
@pytest.mark.no_parallel
async def test_restart_offline_to_terminal_artifact_through_production_observer(monkeypatch, tmp_path):
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
    first = store.build_record(execution_profile_id="outage-e2e", prompt_body="owned prompt")
    follower = store.build_record(execution_profile_id="outage-e2e", prompt_body="follower")
    for record in (first, follower):
        store.write_record(tmp_path, record)
    url = "https://chatgpt.com/g/g-p-original/c/conversation"
    chat = PersistentChat(ag_session_id="isolated-session", project_name="original",
        project_url="https://chatgpt.com/g/g-p-original/project", runtime=runtime,
        config=config, binding_sink=lambda update: None, provider_session_id="conversation",
        chat_url=url, resume_provider_metadata={"unresolved-turn-pending": True,
            "unresolved-turn-id": first["request-id"], "prompt-message-id": "u1",
            "submission-proven": True, "target-id": "old-target"})
    chat.defer_unresolved_reconciliation()
    transport = GptAutoSessionTransport(chat)
    methods, observations, order = [], [], []
    target = {"targetId": "new-target", "type": "page", "url": url, "title": "isolated"}
    snapshot = {"url": url, "composerPresent": True, "composerEditable": True,
        "userCount": 1, "assistantCount": 1, "latestUserId": "u1", "userMessageIds": ["u1"],
        "latestUserText": "owned prompt", "latestAssistantId": "a1", "assistantMessageIds": ["a1"],
        "latestAssistantText": "completed during browser outage", "terminalWitnessAssistantId": "a1",
        "messageRefs": [{"role": "user", "messageId": "u1", "text": "owned prompt", "sequence": 0},
                        {"role": "assistant", "messageId": "a1", "text": "completed during browser outage", "sequence": 1}],
        "domSignals": {"completion-control": True, "more-actions-menu": True}, "generating": False}

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

    async def recover_response():
        await transport.open()
        return await transport.resume_existing(
            SessionPrompt(turn_id=first["request-id"], body="owned prompt"), observations.append,
        )

    loop = asyncio.get_running_loop()
    started = threading.Event()

    def runner(project, record):
        order.append(record["request-id"])
        if record["request-id"] == first["request-id"]:
            started.set()
            response = asyncio.run_coroutine_threadsafe(recover_response(), loop).result(timeout=8)
            output = response.final_summary
            assert response.stop_reason == "end-turn"
        else:
            output = "follower completed"
        return store.transition_record(project, record["request-id"], "completed", updates={"output": output})

    manager.enqueue(tmp_path, first, {"virtual-capacity": 1}, runner)
    try:
        assert await asyncio.to_thread(started.wait, 1)
        manager.enqueue(tmp_path, follower, {"virtual-capacity": 1}, runner)
        await asyncio.sleep(0.4)  # Longer than a CDP connect attempt.
        assert store.read_record(tmp_path, first["request-id"])["state"] == "running"
        assert store.read_record(tmp_path, follower["request-id"])["state"] == "queued"
        async with serve(handler, "127.0.0.1", port, process_request=discovery):
            terminal = await asyncio.to_thread(manager.wait, tmp_path, first["request-id"], timeout_seconds=6)
            next_result = await asyncio.to_thread(manager.wait, tmp_path, follower["request-id"], timeout_seconds=2)
            assert terminal["state"] == next_result["state"] == "completed"
            assert terminal["output"] == "completed during browser outage"
            assert order == [first["request-id"], follower["request-id"]]
            assert chat.target_id == "new-target"
            assert not chat.unresolved_turn_pending
            assert observations
            assert not any(method.startswith("Input.") or method in {"Page.navigate", "Target.activateTarget", "Target.createTarget"} for method in methods)
            await runtime.shutdown()
    finally:
        manager.shutdown()
        if runtime.state != "stopped":
            await runtime.shutdown()
