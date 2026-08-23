"""Phase-0 deterministic ladder gates.

The tests in this module are intentionally non-live.  They prove the harness
can reject accidental network/process use and that the scripted fixtures are
explicit rather than timing-dependent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.providers.adapters.gpt_auto import session_transport
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime

from .deterministic_fixtures import (
    FakeTargetTable,
    Gate,
    NetworkTripwire,
    ProcessTripwire,
    ScriptedCdpClient,
    SnapshotScript,
)
from .test_greenfield_config_urls import valid_config


def test_network_tripwire_rejects_socket_access(monkeypatch: pytest.MonkeyPatch) -> None:
    tripwire = NetworkTripwire()
    tripwire.patch_socket(monkeypatch)
    with pytest.raises(AssertionError, match="network operation"):
        import socket

        socket.create_connection(("example.invalid", 443))
    assert [operation for operation, _ in tripwire.attempts] == [
        "socket.create_connection"
    ]


def test_process_tripwire_rejects_unexpected_launch() -> None:
    tripwire = ProcessTripwire()
    with pytest.raises(AssertionError, match="process launch"):
        tripwire("brave", "--remote-debugging-port=9222")
    assert tripwire.attempts == [("brave", "--remote-debugging-port=9222")]


def test_provider_runtime_construction_is_non_live() -> None:
    runtime = GptAutoProviderRuntime(GptAutoConfig.from_dict(valid_config()))
    assert runtime.state.value == "stopped"
    assert runtime._bridge is None
    assert runtime._gpt_browser is None


@pytest.mark.asyncio
async def test_gate_controls_concurrency_without_sleep() -> None:
    gate = Gate()
    task = asyncio.create_task(gate.wait())
    await gate.entered.wait()
    assert not task.done()
    gate.release.set()
    await task


@pytest.mark.asyncio
async def test_scripted_cdp_client_preserves_call_order_and_errors() -> None:
    client = ScriptedCdpClient()
    client.script("Target.getTargets", {"targetInfos": []})
    client.script("Runtime.evaluate", RuntimeError("protocol failure"))
    assert await client.command("Target.getTargets") == {"targetInfos": []}
    with pytest.raises(RuntimeError, match="protocol failure"):
        await client.command("Runtime.evaluate", {"expression": "1"}, session_id="s-1")
    assert client.calls == [
        ("Target.getTargets", {}, None),
        ("Runtime.evaluate", {"expression": "1"}, "s-1"),
    ]


def test_snapshot_and_target_scripts_are_explicit() -> None:
    snapshots = SnapshotScript({"state": "ready"}, {"state": "generating"})
    assert snapshots.next()["state"] == "ready"
    assert snapshots.next()["state"] == "generating"
    with pytest.raises(AssertionError, match="exhausted"):
        snapshots.next()

    targets = FakeTargetTable({"targetId": "a", "type": "page"})
    targets.add(targetId="b", type="page", openerId="a")
    assert {target["targetId"] for target in targets.as_infos()} == {"a", "b"}
    targets.remove("a")
    assert {target["targetId"] for target in targets.as_infos()} == {"b"}


def test_resume_build_forwards_durable_chat_url_without_submitting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = SimpleNamespace()
    monkeypatch.setattr(session_transport, "get_runtime", lambda _root, _config: runtime)
    transport = session_transport.build_session_transport(
        tmp_path,
        config=valid_config(),
        ag_session_id="ses-resumed",
        binding_sink=lambda _update: None,
        project_name="project",
        resume_provider_ref="conversation-42",
        resume_metadata_hint={
            "project-url": "https://chatgpt.com/g/g-p-project/project",
            "chat-url": "https://chatgpt.com/g/g-p-project/c/conversation-42",
        },
    )
    assert transport.chat.provider_session_id == "conversation-42"
    assert transport.chat.chat_url.endswith("/c/conversation-42")
    assert transport._active_turn is None


def test_resume_build_tolerates_missing_chat_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A missing chat-url must defer to browser-based reconciliation, not fail resume outright."""
    runtime = SimpleNamespace()
    monkeypatch.setattr(session_transport, "get_runtime", lambda _root, _config: runtime)
    transport = session_transport.build_session_transport(
        tmp_path,
        config=valid_config(),
        ag_session_id="ses-resumed",
        binding_sink=lambda _update: None,
        project_name="project",
        resume_provider_ref="conversation-42",
        resume_metadata_hint={
            "project-url": "https://chatgpt.com/g/g-p-project/project",
        },
    )
    assert transport.chat.provider_session_id == "conversation-42"
    assert transport.chat.chat_url is None
    assert transport._active_turn is None


def test_resume_build_rejects_conflicting_chat_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A chat-url that actively conflicts with the provider ref is still a hard failure."""
    runtime = SimpleNamespace()
    monkeypatch.setattr(session_transport, "get_runtime", lambda _root, _config: runtime)
    with pytest.raises(RuntimeError, match="matching project-scoped durable chat-url"):
        session_transport.build_session_transport(
            tmp_path,
            config=valid_config(),
            ag_session_id="ses-resumed",
            binding_sink=lambda _update: None,
            project_name="project",
            resume_provider_ref="conversation-42",
            resume_metadata_hint={
                "project-url": "https://chatgpt.com/g/g-p-project/project",
                "chat-url": "https://chatgpt.com/g/g-p-project/c/some-other-conversation",
            },
        )


def test_resume_build_rejects_unprojected_chat_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A persisted generic ChatGPT conversation must never be reopened."""
    runtime = SimpleNamespace()
    monkeypatch.setattr(session_transport, "get_runtime", lambda _root, _config: runtime)

    with pytest.raises(RuntimeError, match="project-scoped durable chat-url"):
        session_transport.build_session_transport(
            tmp_path,
            config=valid_config(),
            ag_session_id="ses-resumed",
            binding_sink=lambda _update: None,
            project_name="project",
            resume_provider_ref="conversation-42",
            resume_metadata_hint={
                "project-url": "https://chatgpt.com/g/g-p-project/project",
                "chat-url": "https://chatgpt.com/c/conversation-42",
            },
        )


def test_deterministic_selection_excludes_live_modules() -> None:
    root = Path(__file__).parent
    live = {path.name for path in root.glob("*_live.py")}
    deterministic = {
        path.name for path in root.glob("test_*.py") if not path.name.endswith("_live.py")
    }
    assert live
    assert not live & deterministic
