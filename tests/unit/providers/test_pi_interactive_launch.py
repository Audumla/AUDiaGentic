"""HA04: Pi's provider-owned interactive (TUI) launch builder.

Stock Pi only -- AUDiaGentic injects no extensions (footer.ts/follow_up_actions
were removed with the old custom launcher). Kept hand-written as the documented
escape hatch; still returns a ProviderLaunch through the shared dispatch/spawn.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.pi.interactive import (
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
    def __init__(self, args: tuple[str, ...] = (), env: dict[str, str] | None = None) -> None:
        self.extra_args = args
        self.extra_env = env or {}


def _patch(monkeypatch: pytest.MonkeyPatch, *, pi_cfg: dict | None = None) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pi" if name == "pi" else None)
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.interactive.load_pi_config",
        lambda project_root: pi_cfg or {},
    )


def test_missing_pi_cli_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(AudiaGenticError) as excinfo:
        build_interactive_launch(
            tmp_path, provider="audiagentic", model="qwen", agent_runtime=tmp_path / "runtime"
        )

    assert excinfo.value.code == "EXT-PROVCLI-001"


def test_basic_launch_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    agent_runtime = tmp_path / "runtime"

    launch = build_interactive_launch(
        tmp_path, provider="audiagentic", model="qwen3.5", agent_runtime=agent_runtime
    )

    assert launch.executable == "/usr/bin/pi"
    assert launch.args[:4] == ("--provider", "audiagentic", "--model", "qwen3.5")
    assert "--no-extensions" in launch.args  # no MCP -> disable extension discovery
    # No AG extension is injected -- stock Pi only.
    assert "--extension" not in launch.args
    assert launch.environment["HOME"] == str(agent_runtime)
    assert launch.environment["PI_CODING_AGENT_DIR"] == str(agent_runtime / "agent")


def test_tools_mode_maps_to_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, pi_cfg={"tools": {"mode": "mcp-only"}})
    launch = build_interactive_launch(
        tmp_path, provider="p", model="m", agent_runtime=tmp_path / "runtime"
    )
    assert "--no-builtin-tools" in launch.args

    _patch(monkeypatch, pi_cfg={"tools": {"mode": "none"}})
    launch = build_interactive_launch(
        tmp_path, provider="p", model="m", agent_runtime=tmp_path / "runtime"
    )
    assert "--no-tools" in launch.args

    _patch(monkeypatch, pi_cfg={"tools": {"mode": "full"}})
    launch = build_interactive_launch(
        tmp_path, provider="p", model="m", agent_runtime=tmp_path / "runtime"
    )
    assert "--no-tools" not in launch.args
    assert "--no-builtin-tools" not in launch.args


def test_mcp_surface_appended_and_no_extensions_flag_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch)
    surface = _FakeSurface(args=("--mcp-config", "x.json", "--mcp-exclusive"), env={"FOO": "bar"})

    launch = build_interactive_launch(
        tmp_path,
        provider="audiagentic",
        model="qwen3.5",
        agent_runtime=tmp_path / "runtime",
        mcp_surface=surface,
    )

    assert "--no-extensions" not in launch.args
    assert "--mcp-config" in launch.args
    assert "--mcp-exclusive" in launch.args
    assert launch.environment["FOO"] == "bar"


def test_smoke_mode_uses_smoke_args_and_skips_extension_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch)

    launch = build_interactive_launch(
        tmp_path, provider="audiagentic", model="qwen3.5", agent_runtime=tmp_path / "runtime", smoke=True
    )

    assert "-p" in launch.args
    assert "audiagentic-agent-local-ok" in " ".join(launch.args)
    assert "--extension" not in launch.args


def test_lockdown_flags_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, pi_cfg={"lockdown": {"no_skills": True, "no_prompt_templates": False, "no_context_files": True}})

    launch = build_interactive_launch(
        tmp_path, provider="audiagentic", model="qwen3.5", agent_runtime=tmp_path / "runtime"
    )

    assert "--no-skills" in launch.args
    assert "--no-prompt-templates" not in launch.args
    assert "--no-context-files" in launch.args


def test_runner_params_translated_and_appended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)

    launch = build_interactive_launch(
        tmp_path,
        provider="audiagentic",
        model="qwen3.5",
        agent_runtime=tmp_path / "runtime",
        runner_params=_RunnerParams(prompt="hello", verbose=True, mode="text"),
    )

    assert launch.args[-5:] == ("-p", "hello", "--verbose", "--mode", "text")


def test_translate_runner_args_matches_pi_flags() -> None:
    assert translate_runner_args(_RunnerParams(prompt="hi", verbose=True, mode="json")) == [
        "-p", "hi", "--verbose", "--mode", "json",
    ]
    assert translate_runner_args(None) == []
