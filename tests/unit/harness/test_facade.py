from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import audiagentic.runtime.harness as harness


def test_run_agent_translates_runner_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(ctx, provider_id, params, **kw):
        captured["ctx"] = ctx
        captured["provider_id"] = provider_id
        captured["params"] = params
        captured["kw"] = kw
        return 17

    monkeypatch.setattr("audiagentic.runtime.harness.run_common.run_provider_agent", fake_run)
    monkeypatch.setattr(harness, "get_harness_type", lambda project_root=None: "pi")

    result = harness.run_agent(
        SimpleNamespace(project_root=Path(".")),
        harness.RunnerParams(prompt="Reply with exactly: OK", mode="text", verbose=True),
        smoke=False,
    )

    assert result == 17
    assert captured["ctx"].project_root == Path(".")
    assert captured["provider_id"] == "pi"
    assert captured["params"] == harness.RunnerParams(
        prompt="Reply with exactly: OK", mode="text", verbose=True
    )
    assert captured["kw"] == {"smoke": False}
