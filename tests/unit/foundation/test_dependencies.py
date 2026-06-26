from __future__ import annotations

from audiagentic.foundation.components.dependencies import build_dependency_probes, detect_missing
from audiagentic.foundation.workflow.invocation.models import StepResult
from audiagentic.foundation.workflow.invocation.steps import SelectStep, SequenceStep, ShellStep


def _probe(value: bool):
    return lambda: value


def _step(status: str = "ok") -> ShellStep:
    # dry_run=True so it never shells out; returns planned (ok) result
    return ShellStep(id="cmd", command=("echo", "ok"), dry_run=True)


# ---------------------------------------------------------------------------
# detect_missing
# ---------------------------------------------------------------------------

def test_detect_missing_returns_unsatisfied() -> None:
    probes = {"git": _probe(True), "gh": _probe(False), "uv": _probe(False)}
    assert detect_missing(probes) == ["gh", "uv"]


def test_detect_missing_filters_by_names() -> None:
    probes = {"git": _probe(False), "gh": _probe(False)}
    assert detect_missing(probes, ["git"]) == ["git"]


def test_detect_missing_all_satisfied() -> None:
    probes = {"git": _probe(True), "gh": _probe(True)}
    assert detect_missing(probes) == []


def test_all_binaries_probe_requires_every_binary(monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.foundation.components.dependencies.tool_available",
        lambda name: name == "present",
    )
    probes = build_dependency_probes(
        {"thing": {"probe": "all-binaries:present,missing"}}
    )

    assert probes["thing"]() is False


def test_command_probe_reports_success(monkeypatch) -> None:
    class _Result:
        returncode = 0

    monkeypatch.setattr(
        "audiagentic.foundation.components.dependencies.subprocess.run",
        lambda *args, **kwargs: _Result(),
    )
    probes = build_dependency_probes({"thing": {"probe": "command:tool --version"}})

    assert probes["thing"]() is True


def test_command_probe_uses_utf8_replace(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Result:
        returncode = 0

    def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(
        "audiagentic.foundation.components.dependencies.subprocess.run",
        _fake_run,
    )

    probes = build_dependency_probes({"thing": {"probe": "command:tool --version"}})

    assert probes["thing"]() is True
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"


# ---------------------------------------------------------------------------
# SelectStep — core dispatch primitive
# ---------------------------------------------------------------------------

def test_select_step_runs_matching_variant() -> None:
    step = SelectStep(
        id="s",
        select=lambda _: "apt",
        variants={
            "apt": ShellStep(id="apt", command=("echo", "apt"), dry_run=True),
            "winget": ShellStep(id="winget", command=("echo", "winget"), dry_run=True),
        },
    )
    result = step.run({})
    assert result.status in ("ok", "planned")


def test_select_step_skips_when_select_returns_none() -> None:
    step = SelectStep(
        id="s",
        select=lambda _: None,
        variants={"run": ShellStep(id="cmd", command=("echo",), dry_run=True)},
    )
    result = step.run({})
    assert result.status == "skipped"


def test_select_step_uses_fallback_on_missing_variant() -> None:
    fallback = SelectStep(
        id="fallback",
        select=lambda _: "linux",
        variants={"linux": ShellStep(id="sh", command=("echo",), dry_run=True)},
    )
    step = SelectStep(
        id="s",
        select=lambda _: "unknown-pm",
        variants={},
        fallback=fallback,
    )
    result = step.run({})
    assert result.status in ("ok", "planned")


def test_select_step_fails_with_no_variant_no_fallback() -> None:
    step = SelectStep(
        id="s",
        select=lambda _: "apt",
        variants={},
    )
    result = step.run({})
    assert result.status == "failed"
    assert "apt" in (result.reason or "")


# ---------------------------------------------------------------------------
# Dep workflow pattern: probe-guard wrapping an install SelectStep
# ---------------------------------------------------------------------------

def test_dep_skips_when_probe_satisfied() -> None:
    probe = _probe(True)  # already installed
    dep = SelectStep(
        id="git",
        select=lambda _: None if probe() else "run",
        variants={"run": ShellStep(id="install", command=("echo",), dry_run=True)},
    )
    result = dep.run({})
    assert result.status == "skipped"


def test_dep_installs_when_probe_fails() -> None:
    probe = _probe(False)  # not installed
    dep = SelectStep(
        id="git",
        select=lambda _: None if probe() else "run",
        variants={"run": ShellStep(id="install", command=("echo",), dry_run=True)},
    )
    result = dep.run({})
    assert result.status in ("ok", "planned")


def test_sequence_respects_requires_order() -> None:
    order: list[str] = []

    def _tracking(name: str) -> SelectStep:
        def _run(ctx, answers=None):
            order.append(name)
            return StepResult(status="ok")
        s = ShellStep(id=name, command=("echo",), dry_run=True)
        # patch run onto a SelectStep
        sel = SelectStep(id=name, select=lambda _: "run", variants={"run": s})
        object.__setattr__(sel, "run", _run)
        return sel

    gh = _tracking("gh")
    gh_mcp = _tracking("gh-mcp")
    seq = SequenceStep(id="deps", steps=(gh, gh_mcp), fail_fast=False)
    seq.run({})
    assert order == ["gh", "gh-mcp"]
