"""HA04 slice 2: the shared build_launch_spec vocabulary.

Two axes only: runtime *context tokens* (a fixed closed set every launch
shares) and config-driven *flag primitives* (a small general algebra). No
per-provider special logic, no conditionals beyond these primitives.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.adapters.base_runner import build_launch_spec
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports import ProviderLaunch


@pytest.fixture(autouse=True)
def _fake_which(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.cli.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )


def _args(spec_decl, **kw):
    return list(build_launch_spec(spec_decl, **kw).args)


# --- executable resolution ---

def test_returns_provider_launch_with_resolved_executable() -> None:
    spec = build_launch_spec({"executable": "pi", "aliases": ["pi"]})
    assert isinstance(spec, ProviderLaunch)
    assert spec.executable == "/usr/bin/pi"


def test_aliases_default_to_executable() -> None:
    spec = build_launch_spec({"executable": "opencode"})
    assert spec.executable == "/usr/bin/opencode"


# --- context tokens (runtime) ---

def test_prompt_token_emits_only_when_present() -> None:
    assert _args({"executable": "x", "args": ["{prompt}"]}, context={"prompt": "hi"}) == ["hi"]
    assert _args({"executable": "x", "args": ["{prompt}"]}, context={}) == []


def test_model_flags_token() -> None:
    decl = {"executable": "x", "args": ["{model-flags}"], "model-flag": "-m"}
    assert _args(decl, context={"model": "m1"}) == ["-m", "m1"]
    assert _args(decl, context={}) == []  # no model -> nothing


def test_approval_flags_token() -> None:
    decl = {
        "executable": "x",
        "args": ["{approval-flags}"],
        "approval-mode-flags": {"yolo": ["--yolo"]},
    }
    assert _args(decl, context={"approval-mode": "yolo"}) == ["--yolo"]
    assert _args(decl, context={"approval-mode": "auto"}) == []


def test_mcp_and_runner_arg_tokens() -> None:
    decl = {"executable": "x", "args": ["{mcp-args}", "{runner-args}"]}
    assert _args(decl, context={"mcp-args": ("--mcp", "c.json"), "runner-args": ["-p", "q"]}) == [
        "--mcp", "c.json", "-p", "q",
    ]


def test_model_literal_token_formats() -> None:
    decl = {"executable": "x", "args": ["--model={model}"]}
    assert _args(decl, context={"model": "abc"}) == ["--model=abc"]
    assert _args(decl, context={}) == []


def test_literal_passthrough() -> None:
    assert _args({"executable": "x", "args": ["--print", "-q"]}) == ["--print", "-q"]


# --- config flag primitives (static algebra) ---

def test_enum_flags() -> None:
    decl = {"executable": "x", "args": [
        {"enum-flags": {"key": "tools.mode", "cases": {"none": ["--no-tools"], "mcp-only": ["--no-builtin-tools"]}}},
    ]}
    assert _args(decl, config={"tools": {"mode": "none"}}) == ["--no-tools"]
    assert _args(decl, config={"tools": {"mode": "mcp-only"}}) == ["--no-builtin-tools"]
    assert _args(decl, config={"tools": {"mode": "allow"}}) == []  # unmapped case
    assert _args(decl, config={}) == []  # missing key


def test_enum_flags_default() -> None:
    decl = {"executable": "x", "args": [
        {"enum-flags": {"key": "tools.mode", "default": "mcp-only", "cases": {"mcp-only": ["--no-builtin-tools"]}}},
    ]}
    assert _args(decl, config={}) == ["--no-builtin-tools"]


def test_value_flag_optional_and_join() -> None:
    decl = {"executable": "x", "args": [{"value-flag": {"key": "sandbox.config_path", "flag": "--sandbox-config"}}]}
    assert _args(decl, config={"sandbox": {"config_path": "/s.json"}}) == ["--sandbox-config", "/s.json"]
    assert _args(decl, config={"sandbox": {}}) == []
    joined = {"executable": "x", "args": [{"value-flag": {"key": "tools.allow", "flag": "--tools", "join": ","}}]}
    assert _args(joined, config={"tools": {"allow": ["read", "edit"]}}) == ["--tools", "read,edit"]


def test_repeat_value_flag() -> None:
    decl = {"executable": "x", "args": [{"repeat-value-flag": {"key": "extensions.load", "flag": "-e"}}]}
    assert _args(decl, config={"extensions": {"load": ["a.ts", "b.ts"]}}) == ["-e", "a.ts", "-e", "b.ts"]
    assert _args(decl, config={}) == []


def test_boolean_flags_with_default() -> None:
    decl = {"executable": "x", "args": [
        {"boolean-flags": {"default": True, "flags": {
            "lockdown.no_skills": "--no-skills",
            "lockdown.no_prompt_templates": "--no-prompt-templates",
        }}},
    ]}
    # no_skills unset -> default True -> emitted; no_prompt_templates False -> omitted
    assert _args(decl, config={"lockdown": {"no_prompt_templates": False}}) == ["--no-skills"]


def test_unknown_primitive_raises() -> None:
    with pytest.raises(AudiaGenticError) as exc:
        build_launch_spec({"executable": "x", "args": [{"bogus": {}}]})
    assert exc.value.code == "VAL-EXEC-003"


# --- environment block ---

def test_environment_block_and_extra_env() -> None:
    spec = build_launch_spec(
        {"executable": "x", "environment": {"HOME": "{home}", "PI_DIR": "{home}/agent"}},
        context={"env": {"home": "/run/x"}, "extra-env": {"MCP_ENV": "1"}},
    )
    assert dict(spec.environment) == {"HOME": "/run/x", "PI_DIR": "/run/x/agent", "MCP_ENV": "1"}


# --- default template preserves legacy one-shot shape ---

def test_default_template_is_legacy_one_shot() -> None:
    decl = {"executable": "x", "model-flag": "-m", "approval-mode-flags": {"yolo": ["--yolo"]}}
    assert _args(decl, context={"prompt": "p", "model": "m", "approval-mode": "yolo"}) == [
        "--yolo", "-m", "m", "p",
    ]
