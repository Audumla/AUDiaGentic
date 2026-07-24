"""HA03 slice 2: OpenCode's provider-owned interactive (TUI) launch builder."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.opencode.interactive import (
    build_interactive_launch,
    translate_runner_args,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@dataclass
class _RunnerParams:
    prompt: str | None = None
    mode: str | None = None
    verbose: bool = False


class _FakeSurface:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        self.extra_args = ()
        self.extra_env = env or {}


def test_missing_opencode_cli_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(AudiaGenticError) as excinfo:
        build_interactive_launch(
            tmp_path, provider="audiagentic", model="qwen", agent_runtime=tmp_path / "runtime"
        )

    assert excinfo.value.code == "CFG-OCINST-003"


def test_basic_launch_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode" if name == "opencode" else None)

    launch = build_interactive_launch(
        tmp_path, provider="audiagentic", model="qwen3.5", agent_runtime=tmp_path / "runtime"
    )

    assert launch.executable == "/usr/bin/opencode"
    assert launch.args == ()
    assert launch.environment == {}


def test_mcp_surface_env_merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode")
    surface = _FakeSurface(env={"FOO": "bar"})

    launch = build_interactive_launch(
        tmp_path,
        provider="audiagentic",
        model="qwen3.5",
        agent_runtime=tmp_path / "runtime",
        mcp_surface=surface,
    )

    assert launch.environment["FOO"] == "bar"


def test_runner_params_translated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/opencode")

    launch = build_interactive_launch(
        tmp_path,
        provider="audiagentic",
        model="qwen3.5",
        agent_runtime=tmp_path / "runtime",
        runner_params=_RunnerParams(prompt="hello", mode="json"),
    )

    assert launch.args == ("--output-format", "json", "--message", "hello")


def test_translate_runner_args() -> None:
    assert translate_runner_args(_RunnerParams(prompt="hi", mode="json")) == [
        "--output-format", "json", "--message", "hi",
    ]
    assert translate_runner_args(_RunnerParams(mode="text")) == []
    assert translate_runner_args(None) == []
