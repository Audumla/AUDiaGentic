from audiagentic.foundation.steps import ShellStep


def test_compensation_command_uses_runtime_context(monkeypatch) -> None:
    step = ShellStep(
        id="install",
        command=("tool", "install", "{package}"),
        compensate_command=("tool", "remove", "{package}"),
    )
    seen = []
    monkeypatch.setattr(ShellStep, "_execute", lambda self, command, context: seen.append(command) or type("R", (), {"status": "ok"})())
    step.compensate({"package": "demo"})
    assert seen == [("tool", "remove", "demo")]
