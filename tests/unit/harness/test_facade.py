from __future__ import annotations

import audiagentic.runtime.harness as harness


def test_run_agent_translates_runner_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRunnerModule:
        @staticmethod
        def translate_agent_args(params):
            args: list[str] = []
            if params.prompt is not None:
                args.extend(["-p", params.prompt])
            if params.verbose:
                args.append("--verbose")
            if params.mode is not None:
                args.extend(["--mode", params.mode])
            return args

        @staticmethod
        def run_agent(ctx, params, **kw):
            captured["ctx"] = ctx
            captured["params"] = params
            captured["kw"] = kw
            return 17

    monkeypatch.setattr(harness, "_mod", lambda subpath, project_root=None: FakeRunnerModule())

    result = harness.run_agent(
        {"ctx": True},
        harness.RunnerParams(prompt="Reply with exactly: OK", mode="text", verbose=True),
        smoke=False,
    )

    assert result == 17
    assert captured["ctx"] == {"ctx": True}
    assert captured["params"] == ["-p", "Reply with exactly: OK", "--verbose", "--mode", "text"]
    assert captured["kw"] == {"smoke": False}
