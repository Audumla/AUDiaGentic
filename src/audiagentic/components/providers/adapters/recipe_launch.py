"""Build a launch kind's ProviderLaunch from a declarative descriptor block.

The recipe path of ``resolve_launch_builder``: when a provider has no
hand-written ``adapters/<id>/<kind>.py`` builder, its ``<kind>:`` descriptor
block (``interactive:`` / ``acp:``) drives ``build_launch_spec`` instead. The
block is *both* the recipe (executable/args/environment) and its own config
(tools/lockdown/... resolved by the config-flag primitives) — one place owns a
provider's whole launch story for that kind.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import build_launch_spec
from audiagentic.foundation.transports import ProviderLaunch


def _translate_runner_flags(runner_flags: dict[str, Any], runner_params: Any) -> list[str]:
    """Map RunnerParams (prompt/mode/verbose) to flags via a declarative map.

    ``runner-flags`` schema (all optional): ``prompt`` (flag taking the value),
    ``verbose`` (boolean flag), ``mode`` (flag taking the value), and
    ``mode-cases`` ({value: [flags]}) for providers whose mode maps to fixed
    flags (e.g. opencode json -> --output-format json).
    """
    if runner_params is None or not runner_flags:
        return []
    args: list[str] = []
    prompt = getattr(runner_params, "prompt", None)
    mode = getattr(runner_params, "mode", None)
    verbose = getattr(runner_params, "verbose", False)
    if mode is not None and "mode-cases" in runner_flags:
        args.extend(runner_flags["mode-cases"].get(mode, []))
    elif mode is not None and runner_flags.get("mode"):
        args.extend([runner_flags["mode"], str(mode)])
    if verbose and runner_flags.get("verbose"):
        args.append(runner_flags["verbose"])
    if prompt is not None and runner_flags.get("prompt"):
        args.extend([runner_flags["prompt"], str(prompt)])
    return args


def _make_interactive_builder(provider_id: str, block: dict[str, Any]):
    def build_interactive_launch(
        project_root: Path,
        *,
        provider: str,
        model: str,
        agent_runtime: Path,
        mcp_surface: Any = None,
        runner_params: Any = None,
        smoke: bool = False,
    ) -> ProviderLaunch:
        agent_dir = agent_runtime / "agent"
        context: dict[str, Any] = {
            "model": model,
            "prompt": None,
            "runner-args": _translate_runner_flags(block.get("runner-flags", {}), runner_params),
            "mcp-args": tuple(mcp_surface.extra_args) if mcp_surface is not None else (),
            "extra-env": dict(mcp_surface.extra_env) if mcp_surface is not None else {},
            "enable-mcp": mcp_surface is not None,
            "env": {
                "provider": provider,
                "model": model,
                "agent_runtime": str(agent_runtime),
                "agent_dir": str(agent_dir),
                "project_root": str(project_root),
            },
        }
        # {provider}/{model} substitution for literal args (e.g. --provider {provider}).
        spec_decl = dict(block)
        if smoke and block.get("smoke-args") is not None:
            spec_decl["args"] = block["smoke-args"]
        return build_launch_spec(
            spec_decl,
            context={**context, "provider": provider},
            config=block,
        )

    return build_interactive_launch


def _make_acp_builder(provider_id: str, block: dict[str, Any]):
    def build_acp_launch(
        project_root: Path,
        *,
        model_id: str | None = None,
        request_runtime_root: Path | None = None,
        mcp_surface: Any = None,
    ) -> ProviderLaunch:
        context: dict[str, Any] = {
            "model": model_id,
            "mcp-args": tuple(mcp_surface.extra_args) if mcp_surface is not None else (),
            "extra-env": dict(mcp_surface.extra_env) if mcp_surface is not None else {},
            "env": {
                "model": model_id or "",
                "project_root": str(project_root),
                "request_runtime_root": str(request_runtime_root or ""),
            },
        }
        return build_launch_spec(dict(block), context=context, config=block)

    return build_acp_launch


def translate_recipe_runner_args(provider_id: str, runner_params: Any, kind: str = "interactive") -> list[str]:
    """Translate RunnerParams via a provider's recipe ``runner-flags`` block.

    The declarative source for a recipe-driven provider's RunnerParams->flags
    mapping (the escape-hatch equivalent lives in the hand-written builder).
    Returns [] when the provider has no such recipe block.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptor = all_descriptors().get(provider_id)
    block = getattr(descriptor, kind, None) if descriptor else None
    if not block:
        return []
    return _translate_runner_flags(block.get("runner-flags", {}), runner_params)


def descriptor_launch_builder(provider_id: str, kind: str):
    """Return a recipe-backed launch builder for *kind*, or None if undeclared.

    Reads the provider descriptor's ``interactive:`` / ``acp:`` block. Returns
    None when the block is absent — the provider simply does not support that
    launch kind declaratively (and had no hand-written builder either).
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptor = all_descriptors().get(provider_id)
    block = getattr(descriptor, kind, None) if descriptor else None
    if not block:
        return None
    if kind == "interactive":
        return _make_interactive_builder(provider_id, block)
    if kind == "acp":
        return _make_acp_builder(provider_id, block)
    return None


__all__ = ["descriptor_launch_builder"]
