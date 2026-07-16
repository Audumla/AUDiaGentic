"""Recipe materialization — frozen template + parameters -> probes and steps.

Accepts Mapping[str, str] only at the owner boundary. Sensitive parameter
values are redacted from errors, logs, plans, and results. Substitution
uses the existing strict_substitute factory; unknown {NAME} placeholders fail.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.steps.factory import (
    build_steps_from_defs,
    strict_substitute,
)
from audiagentic.foundation.toolchains.probes import (
    CommandProbe,
    CompositeHealthCheck,
    ConfigKeyCheck,
    FileExistsCheck,
    Probe,
    check_with_retry,
    safe_command_parts,
)

from .recipe_loader import DeclarativeRecipeTemplate, ValidatedProbeTemplate, ValidatedStepTemplate

_mat_err = make_error_factory("VAL", "MAT", "recipe-materializer")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedParameters:
    """Frozen normalized parameters after validation and defaults."""

    values: dict[str, str]
    sensitive_names: frozenset[str] = field(default_factory=frozenset)

    def substitute(self, text: str) -> str:
        """Apply strict {NAME} substitution to a string."""
        return strict_substitute(text, self.values, path="materializer")


def _resolve_parameters(
    template: DeclarativeRecipeTemplate,
    raw_params: dict[str, str],
) -> ResolvedParameters:
    """Validate required/unknown values, apply defaults, freeze."""
    result: dict[str, str] = {}
    sensitive: set[str] = set()

    # Build required set and default map
    by_name: dict[str, Any] = {}
    for p in template.parameters:
        by_name[p.name] = p
        if p.is_sensitive:
            sensitive.add(p.name)

    # Apply defaults first
    for p in template.parameters:
        if not p.required and p.default is not None:
            result[p.name] = p.default

    # Override with supplied values
    for name, value in raw_params.items():
        if name not in by_name:
            raise _mat_err(1, f"unknown parameter {name!r}",
                          parameter=name)
        result[name] = value

    # Check required
    for p in template.parameters:
        if p.required and p.name not in result:
            raise _mat_err(2, f"required parameter {p.name!r} not provided",
                          parameter=p.name)

    return ResolvedParameters(
        values=dict(sorted(result.items())),
        sensitive_names=frozenset(sensitive),
    )


# ---------------------------------------------------------------------------
# Probe construction
# ---------------------------------------------------------------------------

def _build_probe(
    probe: ValidatedProbeTemplate,
    params: ResolvedParameters,
) -> Probe:
    """Map a validated probe template to an existing typed Probe."""
    data = probe.data
    ptype = data["type"]

    if ptype == "command":
        cmd = data["command"]
        if isinstance(cmd, str):
            resolved = params.substitute(cmd)
            parts = safe_command_parts(resolved)
        elif isinstance(cmd, list):
            parts = [params.substitute(str(c)) for c in cmd]
        else:
            raise _mat_err(3, "invalid command type in probe")

        return CommandProbe(
            command=tuple(parts),
            expect_exit=data.get("expect-exit"),
            output_pattern=data.get("output-pattern"),
            timeout=int(data.get("timeout", 30)),
        )

    if ptype == "file-exists":
        return FileExistsCheck(
            path=params.substitute(data["path"]),
            content_pattern=data.get("content-pattern"),
        )

    if ptype == "config-key":
        kp = data["key-path"]
        if isinstance(kp, str):
            key_path = tuple(params.substitute(kp).split("."))
        else:
            key_path = tuple(params.substitute(str(k)) for k in kp)

        return ConfigKeyCheck(
            path=params.substitute(data["path"]),
            key_path=key_path,
            expected_value=params.substitute(data["expected-value"])
            if data.get("expected-value") is not None
            else None,
        )

    if ptype == "composite":
        checks = tuple(
            _build_probe(
                ValidatedProbeTemplate(type=ct["type"], data=ct),
                params,
            )
            for ct in data.get("checks", [])
        )

        composite = CompositeHealthCheck(
            checks=checks,
            mode=data.get("mode", "and"),
            threshold=int(data.get("threshold", 1)),
        )

        retries = int(data.get("retries", 0))
        delay = float(data.get("delay-seconds", 0.0))
        if retries > 0:
            return _RetryProbe(composite, retries=retries, delay=delay)
        return composite

    raise _mat_err(4, f"unknown probe type {ptype!r}")


class _RetryProbe:
    """Thin wrapper that applies check_with_retry to any Probe."""

    def __init__(self, inner: Probe, retries: int = 0, delay: float = 0.0) -> None:
        self._inner = inner
        self._retries = retries
        self._delay = delay

    def check(self, context: dict[str, Any] | None = None) -> Any:
        return check_with_retry(
            self._inner,
            retries=self._retries,
            delay_seconds=self._delay,
            context=context,
        )


# ---------------------------------------------------------------------------
# Step construction
# ---------------------------------------------------------------------------

_KEBAB_TO_SNAKE = {
    "key-path": "key_path",
    "compensate-command": "compensate_command",
    "fail-fast": "fail_fast",
    "compensate-on-failure": "compensate_on_failure",
    "create-parents": "create_parents",
    "comment-prefix": "comment_prefix",
}


def _normalize_step_defn(defn: dict[str, Any]) -> dict[str, Any]:
    """Convert kebab-case schema field names to snake_case factory names."""
    return {
        _KEBAB_TO_SNAKE.get(k, k): v for k, v in defn.items()
    }


def _build_steps(
    steps: tuple[ValidatedStepTemplate, ...],
    params: ResolvedParameters,
    recipe_id: str,
) -> list[Any]:
    """Map validated step templates to existing step factory instances."""
    step_defs = []
    for s in steps:
        defn = dict(s.data)
        # Normalize kebab-case -> snake_case for factory
        defn = _normalize_step_defn(defn)
        # Substitute templated string fields
        defn = _substitute_step_defn(defn, params)
        step_defs.append(defn)

    return build_steps_from_defs(step_defs, params.values, recipe_id=recipe_id)


def _substitute_step_defn(
    defn: dict[str, Any],
    params: ResolvedParameters,
) -> dict[str, Any]:
    """Apply strict substitution to step definition string fields.

    Must be called AFTER _normalize_step_defn so field names are snake_case.
    """
    result = dict(defn)

    # Substitute command fields
    cmd = result.get("command")
    if isinstance(cmd, str):
        result["command"] = params.substitute(cmd)
    elif isinstance(cmd, list):
        result["command"] = [params.substitute(str(c)) for c in cmd]

    comp_cmd = result.get("compensate_command")
    if isinstance(comp_cmd, list):
        result["compensate_command"] = [params.substitute(str(c)) for c in comp_cmd]

    cwd = result.get("cwd")
    if isinstance(cwd, str):
        result["cwd"] = params.substitute(cwd)

    env = result.get("env")
    if isinstance(env, dict):
        result["env"] = {
            k: params.substitute(v) for k, v in env.items()
        }

    path = result.get("path")
    if isinstance(path, str):
        result["path"] = params.substitute(path)

    kp = result.get("key_path")
    if isinstance(kp, str):
        result["key_path"] = params.substitute(kp)
    elif isinstance(kp, list):
        result["key_path"] = [params.substitute(str(k)) for k in kp]

    value = result.get("value")
    if isinstance(value, str):
        result["value"] = params.substitute(value)

    content = result.get("content")
    if isinstance(content, str):
        result["content"] = params.substitute(content)

    prompt = result.get("prompt")
    if isinstance(prompt, str):
        result["prompt"] = params.substitute(prompt)

    return result


# ---------------------------------------------------------------------------
# Public materialization API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaterializedRecipe:
    """Fully resolved recipe: probes and steps, ready for execution."""

    recipe_id: str
    recipe_version: str
    probe: Probe | None = None
    install_steps: tuple[Any, ...] = field(default_factory=tuple)
    configure_steps: tuple[Any, ...] = field(default_factory=tuple)
    verify: Probe | None = None
    uninstall_steps: tuple[Any, ...] = field(default_factory=tuple)
    dry_run_steps: tuple[Any, ...] = field(default_factory=tuple)
    resolved_params: ResolvedParameters | None = None


def materialize_recipe(
    template: DeclarativeRecipeTemplate,
    raw_params: dict[str, str],
) -> MaterializedRecipe:
    """Resolve a frozen template with owner-supplied parameters.

    Accepts Mapping[str, str] only at the owner boundary. Validates required/
    unknown values, applies defaults, and constructs typed probes and steps
    using existing factories.

    Sensitive parameter names/values are redacted from errors and logs.
    """
    params = _resolve_parameters(template, raw_params)

    # Build probe
    probe: Probe | None = None
    if template.lifecycle.probe:
        probe = _build_probe(template.lifecycle.probe, params)

    # Build verify probe
    verify: Probe | None = None
    if template.lifecycle.verify:
        verify = _build_probe(template.lifecycle.verify, params)

    # Build steps
    recipe_id = template.recipe_id
    install_steps = tuple(
        _build_steps(template.lifecycle.install_steps, params, recipe_id)
    )
    configure_steps = tuple(
        _build_steps(template.lifecycle.configure_steps, params, recipe_id)
    )
    uninstall_steps = tuple(
        _build_steps(template.lifecycle.uninstall_steps, params, recipe_id)
    )
    dry_run_steps = tuple(
        _build_steps(template.lifecycle.dry_run_steps, params, recipe_id)
    )

    return MaterializedRecipe(
        recipe_id=recipe_id,
        recipe_version=template.recipe_version,
        probe=probe,
        install_steps=install_steps,
        configure_steps=configure_steps,
        verify=verify,
        uninstall_steps=uninstall_steps,
        dry_run_steps=dry_run_steps,
        resolved_params=params,
    )


__all__ = [
    "MaterializedRecipe",
    "materialize_recipe",
    "ResolvedParameters",
]
