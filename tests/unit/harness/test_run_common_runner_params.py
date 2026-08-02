"""Regression: run_provider_agent must not pass a raw list[str] runner_params
into prepare_interactive_provider_launch — that crashes provider adapters'
translate_runner_args() (e.g. Pi's), which expects a RunnerParams object with
.prompt/.verbose/.mode attributes, not `[].prompt`.

Real crash this reproduces (user-reported, 2026-07-29): running `audiagentic`
with no extra CLI args passes runner_params=[] all the way from
launch.py::_cmd_launch -> run_agent -> run_provider_agent ->
prepare_interactive_provider_launch -> build_interactive_launch ->
translate_runner_args([]) -> AttributeError: 'list' object has no attribute
'prompt'. run_provider_agent already has correct list-vs-RunnerParams
handling for the runner_args-appended-after-command path (see the
isinstance(runner_params, list) branch later in the function) -- it just
never applied that same guard before calling the launch builder.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.runtime.harness.context import AgentContext


class _StopAfterLaunchPrepare(Exception):
    """Raised to short-circuit run_provider_agent right after the call under
    test, so this test never needs to simulate a real model endpoint or
    subprocess execution."""


def _make_ctx(tmp_path: Path) -> AgentContext:
    return AgentContext(
        project_root=tmp_path,
        agent_work=tmp_path / "work",
        agent_log_dir=tmp_path / "logs",
        endpoint="http://127.0.0.1:0",
        model="test-model",
        model_profile={},
        profile_name="default",
        provider="pi",
        embedded_rig=False,
        enable_mcp=False,
        agent_runtime=tmp_path / "runtime",
    )


@pytest.mark.parametrize("runner_params", [[], ["--foo", "bar"]])
def test_list_runner_params_not_passed_to_launch_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner_params: list[str],
) -> None:
    from audiagentic.components.providers import providers_api
    from audiagentic.runtime.harness import run_common

    captured: dict[str, object] = {}

    def fake_prepare(*args, **kwargs):
        captured.update(kwargs)
        raise _StopAfterLaunchPrepare()

    monkeypatch.setattr(providers_api, "prepare_interactive_provider_launch", fake_prepare)

    ctx = _make_ctx(tmp_path)
    with pytest.raises(_StopAfterLaunchPrepare):
        run_common.run_provider_agent(ctx, "pi", runner_params, smoke=False)

    # The launch builder must never see the raw list — a real RunnerParams
    # object or None only. The list form is appended to the command later,
    # in run_provider_agent's own runner_args handling, not translated here.
    assert captured["runner_params"] is None


def test_real_runner_params_object_passed_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from audiagentic.components.providers import providers_api
    from audiagentic.runtime.harness import run_common

    class _FakeRunnerParams:
        prompt = "hello"
        verbose = False
        mode = None

    captured: dict[str, object] = {}

    def fake_prepare(*args, **kwargs):
        captured.update(kwargs)
        raise _StopAfterLaunchPrepare()

    monkeypatch.setattr(providers_api, "prepare_interactive_provider_launch", fake_prepare)

    ctx = _make_ctx(tmp_path)
    params = _FakeRunnerParams()
    with pytest.raises(_StopAfterLaunchPrepare):
        run_common.run_provider_agent(ctx, "pi", params, smoke=False)

    assert captured["runner_params"] is params
