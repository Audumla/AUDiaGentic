"""Golden tests for provider execution adapters (AR12 acceptance oracle).

Captured from the pre-refactor adapter implementations: exact command lists
for a fixture packet/provider-config and the normalized result payloads for
fixture stdout samples. The shared YAML-driven pipeline must reproduce these
byte-for-byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError

_PACKET_CTX = {
    "job-id": "job_1",
    "packet-id": "pkt_1",
    "prompt-id": "prm_1",
    "provider-id": None,  # set per provider
    "surface": "cli",
    "workflow-profile": "standard",
    "prompt-body": "do the thing",
    "stream-controls": {},
}

_PROVIDER_CFG = {
    "default-model": "model-x",
    "access-mode": "cli",
    "execution-policy": {"permission-mode": "yolo"},
}


@dataclass
class _FakeCompleted:
    stdout: str
    stderr: str = ""
    returncode: int = 0


def _expected_prompt(provider_id: str, title: str) -> str:
    return (
        f"Execution request for {title}. request=None provider={provider_id} model=model-x. "
        "Return a concise execution summary or the blocking reason if execution "
        f"is impossible. Prompt body: do the thing"
    )


def _run_with_fakes(monkeypatch, provider_id: str, stdout: str):
    """Execute a provider run() with streaming and executable resolution faked.

    Patches every module that may host the pipeline internals (the legacy
    per-adapter modules and the shared runner), so the goldens are valid
    before and after the consolidation.
    """
    import importlib

    captured: dict = {}

    def fake_stream(command, *, cwd=None, stdout_sinks=None, stderr_sinks=None, **kw):
        captured["command"] = list(command)
        captured["cwd"] = cwd
        return _FakeCompleted(stdout=stdout)

    modules = []
    try:
        modules.append(importlib.import_module(
            f"audiagentic.components.providers.adapters.{provider_id.replace('-', '_')}.adapter"
        ))
    except ModuleNotFoundError:
        pass
    try:
        modules.append(importlib.import_module(
            "audiagentic.components.providers.adapters.base_runner"
        ))
    except ModuleNotFoundError:
        pass
    patched_any = False
    for mod in modules:
        if hasattr(mod, "run_streaming_command"):
            monkeypatch.setattr(mod, "run_streaming_command", fake_stream)
            patched_any = True
        if hasattr(mod, "require_executable"):
            monkeypatch.setattr(mod, "require_executable", lambda pid, *a: f"/bin/{pid}")
        if hasattr(mod, "build_extractor_stream_sinks"):
            monkeypatch.setattr(mod, "build_extractor_stream_sinks", lambda *a, **k: ([], []))
    assert patched_any, f"no pipeline module found for {provider_id}"

    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": provider_id})
    result = execute_provider(provider_id=provider_id, packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))
    return result, captured


def test_qwen_golden_command_and_completion(monkeypatch):
    payload = {"kind": "adhoc", "summary": "done", "status": "ok"}
    result, captured = _run_with_fakes(monkeypatch, "qwen", json.dumps(payload))

    assert captured["command"] == [
        "/bin/qwen",
        "--yolo",
        "-m",
        "model-x",
        _expected_prompt("qwen", "Qwen"),
    ]
    assert result["status"] == "ok"
    assert result["provider-id"] == "qwen"
    assert result["model"] == "model-x"
    assert result["output"] == json.dumps(payload)
    completion = result["completion"]
    assert completion["provider-id"] == "qwen"
    assert completion["result-source"] == "stdout-json"
    assert completion["subject"] == payload


def test_qwen_synthetic_fallback_on_plain_text(monkeypatch):
    result, _captured = _run_with_fakes(monkeypatch, "qwen", "just some text")
    assert result["completion"]["result-source"] != "stdout-json"
    assert result["output"] == "just some text"


def test_copilot_golden_command(monkeypatch):
    payload = {"kind": "adhoc", "summary": "done"}
    result, captured = _run_with_fakes(monkeypatch, "copilot", json.dumps(payload))

    assert captured["command"] == [
        "/bin/copilot",
        "copilot",
        "suggest",
        "-t",
        "shell",
        _expected_prompt("copilot", "Copilot"),
    ]
    assert result["provider-id"] == "copilot"
    assert result["completion"]["subject"] == payload


def test_gemini_prefers_packet_model_over_provider_default(monkeypatch):
    """MO10 regression: gemini/adapter.py used to read provider_cfg['default-model']
    directly, ignoring any model-id resolved by gateway dispatch into packet_ctx.
    Both the -m flag and the descriptive prompt text must honor the packet model."""
    import importlib

    captured: dict = {}

    def fake_stream(command, *, cwd=None, stdout_sinks=None, stderr_sinks=None, **kw):
        captured["command"] = list(command)
        return _FakeCompleted(stdout=json.dumps({"kind": "adhoc", "summary": "done"}))

    mod = importlib.import_module("audiagentic.components.providers.adapters.gemini.adapter")
    monkeypatch.setattr(mod, "run_streaming_command", fake_stream)
    monkeypatch.setattr(mod, "require_executable", lambda pid, *a: f"/bin/{pid}")
    monkeypatch.setattr(mod, "build_extractor_stream_sinks", lambda *a, **k: ([], []))

    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": "gemini", "model-id": "packet-model"})
    provider_cfg = dict(_PROVIDER_CFG, **{"default-model": "provider-default-model"})
    execute_provider(provider_id="gemini", packet_ctx=ctx, provider_cfg=provider_cfg)

    assert "-m" in captured["command"]
    assert captured["command"][captured["command"].index("-m") + 1] == "packet-model"
    assert "provider-default-model" not in captured["command"]
    prompt = captured["command"][captured["command"].index("-p") + 1]
    assert "model=packet-model" in prompt
    assert "provider-default-model" not in prompt


def test_gemini_falls_back_to_provider_default_without_packet_model(monkeypatch):
    import importlib

    captured: dict = {}

    def fake_stream(command, *, cwd=None, stdout_sinks=None, stderr_sinks=None, **kw):
        captured["command"] = list(command)
        return _FakeCompleted(stdout=json.dumps({"kind": "adhoc", "summary": "done"}))

    mod = importlib.import_module("audiagentic.components.providers.adapters.gemini.adapter")
    monkeypatch.setattr(mod, "run_streaming_command", fake_stream)
    monkeypatch.setattr(mod, "require_executable", lambda pid, *a: f"/bin/{pid}")
    monkeypatch.setattr(mod, "build_extractor_stream_sinks", lambda *a, **k: ([], []))

    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": "gemini"})
    execute_provider(provider_id="gemini", packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))

    assert captured["command"][captured["command"].index("-m") + 1] == "model-x"


@pytest.mark.parametrize(
    ("provider_id", "aliases"),
    [
        ("goose", ("goose",)),
        ("aider", ("aider",)),
        ("plandex", ("plandex", "pdx")),
        ("openhands", ("openhands", "openhands-cli")),
    ],
)
def test_probe_stub_providers(monkeypatch, provider_id: str, aliases: tuple[str, ...]):
    probed: list = []

    def fake_require(pid, *a):
        probed.append((pid, a))
        return f"/bin/{pid}"

    import audiagentic.components.providers.adapters._stubs as stubs
    monkeypatch.setattr(stubs, "require_executable", fake_require, raising=False)
    try:
        import audiagentic.components.providers.adapters.base_runner as base_runner
        monkeypatch.setattr(base_runner, "require_executable", fake_require, raising=False)
    except ModuleNotFoundError:
        pass

    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": provider_id})
    result = execute_provider(provider_id=provider_id, packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))

    assert result["status"] == "stubbed"
    assert result["provider-id"] == provider_id
    assert result["executable"] == f"/bin/{provider_id}"
    assert "not wired yet" in result["output"]
    assert probed and probed[0][0] == provider_id


def test_roo_execution_unsupported():
    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": "roo"})
    with pytest.raises(AudiaGenticError, match="CON-ROO-001"):
        execute_provider(provider_id="roo", packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))


def test_fixture_provider_yaml_only_execution(monkeypatch):
    """A provider with only an execution: block runs through the shared pipeline."""
    import audiagentic.components.providers.adapters.base_runner as base_runner
    from audiagentic.components.providers.descriptors.base import (
        Capability,
        LaunchSpec,
        ProviderDescriptor,
    )
    from audiagentic.components.providers.descriptors.registry import register
    from audiagentic.components.providers.services.execution.execution import execute_provider

    register(ProviderDescriptor(
        provider_id="fixture-exec",
        display_name="Fixture Exec",
        capabilities=(
            Capability(
                kind="launch",
                mechanism=LaunchSpec(
                    recipes={
                        "execution": {
                            "mode": "cli",
                            "executable": "fixture-exec",
                            "aliases": ["fixture-exec"],
                            "prompt-title": "Fixture",
                            "error-code": "EXT-FIX-001",
                            "args-template": ["run", "{model-flags}", "{prompt}"],
                            "model-flag": "--model",
                        },
                    },
                ),
            ),
        ),
    ))

    captured: dict = {}

    def fake_stream(command, *, cwd=None, stdout_sinks=None, stderr_sinks=None, **kw):
        captured["command"] = list(command)
        return _FakeCompleted(stdout=json.dumps({"kind": "adhoc", "summary": "hi"}))

    monkeypatch.setattr(base_runner, "run_streaming_command", fake_stream)
    monkeypatch.setattr(base_runner, "require_executable", lambda pid, *a: "/bin/fx")
    monkeypatch.setattr(base_runner, "build_extractor_stream_sinks", lambda *a, **k: ([], []))

    ctx = dict(_PACKET_CTX, **{"provider-id": "fixture-exec"})
    result = execute_provider(provider_id="fixture-exec", packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))

    assert captured["command"][0:2] == ["/bin/fx", "run"]
    assert captured["command"][2:4] == ["--model", "model-x"]
    assert result["status"] == "ok"
    assert result["completion"]["subject"] == {"kind": "adhoc", "summary": "hi"}


def test_continue_ok_stub():
    from audiagentic.components.providers.services.execution.execution import execute_provider

    ctx = dict(_PACKET_CTX, **{"provider-id": "continue"})
    result = execute_provider(provider_id="continue", packet_ctx=ctx, provider_cfg=dict(_PROVIDER_CFG))
    assert result["status"] == "ok"
    assert result["provider-id"] == "continue"
    assert result["output"] == "stubbed-response"
