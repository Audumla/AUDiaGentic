"""Typed step factory with explicit registry owned by foundation.steps.

The ``type`` field in a step descriptor selects only a registered step
constructor.  Dotpath/callable resolution happens at the descriptor/config
boundary, not as a hidden cross-component lookup in this package.

Built-in types register directly and idempotently — no importlib module-name
string table (Architecture Standards §1.1).
"""
from __future__ import annotations

import logging
import re as _re
from collections.abc import Callable
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import make_error_factory

from .callable import CallableStep
from .control import ConditionalStep, ConfirmStep, SelectStep
from .sequence import SequenceStep
from .shell import PlatformOverrides, ShellStep
from .structured import ConfigSetStep, ManagedBlockStep, WriteFileStep

logger = logging.getLogger(__name__)

_step_error = make_error_factory("VAL", "STEP", "step-factory")
_sub_error = make_error_factory("VAL", "STUB", "step-substitution")

StepConstructor = Callable[..., Any]


class StepFactory(Protocol):
    """Typed step factory protocol."""

    def build(self, data: dict[str, Any]) -> Any: ...

    def registered_types(self) -> list[str]: ...


class _Registry:
    """Simple typed registry for step constructors."""

    def __init__(self) -> None:
        self._types: dict[str, StepConstructor] = {}

    def register(self, type_name: str, constructor: StepConstructor) -> None:
        if type_name in self._types:
            raise _step_error(1, f"duplicate step type {type_name!r}")
        self._types[type_name] = constructor

    def get(self, type_name: str) -> StepConstructor | None:
        return self._types.get(type_name)

    def all_types(self) -> list[str]:
        return sorted(self._types.keys())


_REGISTRY = _Registry()


# ---------------------------------------------------------------------------
# Substitution utilities (strict build-time and lenient run-time)
# ---------------------------------------------------------------------------

def strict_substitute(value: Any, params: dict[str, str], path: str = "") -> Any:
    """Recursively substitute ``{KEY}`` placeholders with strict validation.

    All ``{WORD}`` patterns must have a corresponding key in *params*; unknown
    keys raise **VAL-STUB-002**.  Literal braces that do not match a known param
    key are preserved as-is, so JSON content with structural braces works.

    Args:
        value: String, list, or dict to substitute into (non-string scalars pass through).
        params: Mapping of placeholder names to replacement values.
        path: Dotpath for error messages.

    Returns:
        Value with all known placeholders replaced; non-string types unchanged.
    """
    _PATTERN = _re.compile(r'\{(\w+)\}')

    if isinstance(value, str):
        matches = _PATTERN.findall(value)
        for match in matches:
            if match not in params:
                raise _sub_error(
                    2,
                    f"unknown placeholder {{{match}}} at {path or 'root'}",
                    placeholder=match,
                    path=path,
                )
        try:
            return _PATTERN.sub(lambda m: params[m.group(1)], value)
        except Exception:
            raise _sub_error(
                2,
                f"substitution error at {path or 'root'}",
                path=path,
            )
    if isinstance(value, list):
        return [strict_substitute(item, params, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            k: strict_substitute(v, params, f"{path}.{k}")
            for k, v in value.items()
        }
    return value


def lenient_substitute(text: str, params: dict[str, str]) -> str:
    """Replace ``{KEY}`` placeholders in a raw string, leniently.

    Unlike :func:`strict_substitute`, this leaves unknown or unset placeholders
    as literal text.  Use for free-form command strings (e.g. status probes)
    where an absent optional value must not fail.
    """
    if not text:
        return text
    for key, value in params.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _drop_empty_flags(command: list[str]) -> list[str]:
    """Drop ``--flag=`` args where the value is empty after substitution.

    This is a factory-time transform for provisioning step construction:
    when an optional recipe parameter is absent, the command tuple may contain
    ``--bank-id=`` which should not be passed to the child process.  Command
    element ``cmd[0]`` (the binary) never starts with ``--`` so this is safe.
    """
    return [a for a in command if not (a.startswith("--") and a.endswith("="))]


# ---------------------------------------------------------------------------
# Builtin registration
# ---------------------------------------------------------------------------

def _register_builtins() -> None:
    """Register built-in step types idempotently."""
    _REGISTRY.register("shell", _build_shell)
    _REGISTRY.register("callable", _build_callable)
    _REGISTRY.register("sequence", _build_sequence)
    _REGISTRY.register("confirm", _build_confirm)
    _REGISTRY.register("select", _build_select)
    _REGISTRY.register("conditional", _build_conditional)
    _REGISTRY.register("config-set", _build_config_set)
    _REGISTRY.register("write-file", _build_write_file)
    _REGISTRY.register("managed-block", _build_managed_block)


# ---------------------------------------------------------------------------
# Step builders (called by factory or batch builder)
# ---------------------------------------------------------------------------

def _build_shell(data: dict[str, Any], params: dict[str, str] | None = None) -> ShellStep:
    command = data["command"]

    # String commands are only valid in shell mode; wrap as single-element tuple.
    if isinstance(command, str):
        cmd_str = strict_substitute(command, params, f"step.{data.get('id', 'shell')}.command") if params is not None else command
        return ShellStep(
            id=data.get("id", "shell"),
            command=(cmd_str,),
            timeout=data.get("timeout", 300),
            dry_run=data.get("dry_run", False),
            cwd=data.get("cwd"),
            env=data.get("env"),
            platform=None,
            compensate_command=None,
            shell=True,
        )

    cmd = list(command) if isinstance(command, list) else list(command)

    # Strict build-time substitution for recipe-driven construction
    if params is not None and isinstance(cmd, list):
        cmd = strict_substitute(cmd, params, f"step.{data.get('id', 'shell')}.command")
        # Drop empty --flag= args after substitution
        cmd = _drop_empty_flags(cmd)

    cmd = tuple(cmd)

    compensate_command = None
    if "compensate_command" in data:
        comp = list(data["compensate_command"])
        if params is not None:
            comp = strict_substitute(comp, params, f"step.{data.get('id', 'shell')}.compensate_command")
            comp = _drop_empty_flags(comp)
        compensate_command = tuple(comp)

    cwd = data.get("cwd")
    if params is not None and cwd is not None:
        cwd = strict_substitute(cwd, params, f"step.{data.get('id', 'shell')}.cwd")

    env = data.get("env")
    if params is not None and env is not None:
        env = strict_substitute(env, params, f"step.{data.get('id', 'shell')}.env")

    platform = None
    if "platform" in data:
        p = data["platform"]
        platform = PlatformOverrides(
            win=tuple(p["win"]) if isinstance(p.get("win"), list) else p.get("win"),
            darwin=tuple(p["darwin"]) if isinstance(p.get("darwin"), list) else p.get("darwin"),
            linux=tuple(p["linux"]) if isinstance(p.get("linux"), list) else p.get("linux"),
        )
    return ShellStep(
        id=data.get("id", "shell"),
        command=cmd,
        timeout=data.get("timeout", 300),
        dry_run=data.get("dry_run", False),
        cwd=cwd,
        env=env,
        platform=platform,
        compensate_command=compensate_command,
        shell=data.get("shell", False),
    )


def _build_callable(data: dict[str, Any]) -> CallableStep:
    from audiagentic.foundation.config.refs import resolve_ref

    fn = resolve_ref(data["fn"])
    return CallableStep(
        id=data.get("id", "callable"),
        fn=fn,
        dry_run=data.get("dry_run", False),
    )


def _build_sequence(data: dict[str, Any], params: dict[str, str] | None = None) -> SequenceStep:
    steps = tuple(build_step(s, params=params) for s in data.get("steps", []))
    return SequenceStep(
        steps,
        id=data.get("id", "sequence"),
        fail_fast=data.get("fail_fast", True),
        compensate_on_failure=data.get("compensate_on_failure", False),
    )


def _build_confirm(data: dict[str, Any]) -> ConfirmStep:
    return ConfirmStep(
        id=data.get("id", "confirm"),
        prompt=data["prompt"],
        default=data.get("default", "yes"),
    )


def _build_select(data: dict[str, Any], params: dict[str, str] | None = None) -> SelectStep:
    from audiagentic.foundation.config.refs import resolve_ref

    select_fn = resolve_ref(data["select"])
    fallback_ref = data.get("fallback")
    return SelectStep(
        id=data.get("id", "select"),
        select=select_fn,
        variants={k: build_step(v, params=params) for k, v in data.get("variants", {}).items()},
        fallback=resolve_ref(fallback_ref) if fallback_ref else None,
    )


def _build_conditional(data: dict[str, Any], params: dict[str, str] | None = None) -> ConditionalStep:
    return ConditionalStep(
        id=data.get("id", "conditional"),
        condition_key=data["condition_key"],
        when_true=build_step(data["when_true"], params=params),
        when_false=build_step(data["when_false"], params=params) if "when_false" in data else None,
    )


def _build_config_set(data: dict[str, Any], params: dict[str, str] | None = None) -> ConfigSetStep:
    kp = data.get("key_path")
    if isinstance(kp, str):
        key_path = tuple(kp.split("."))
    elif kp is not None:
        key_path = tuple(kp)
    else:
        raise _step_error(1, "config-set step missing 'key_path'")

    value = data.get("value")
    if params is not None and value is not None:
        value = strict_substitute(value, params, f"step.{data.get('id', 'config-set')}.value")

    return ConfigSetStep(
        id=data.get("id", "config-set"),
        path=data["path"],
        key_path=key_path,
        value=value,
        registry=data.get("registry"),
        recipe_id=data.get("recipe_id"),
    )


def _build_write_file(data: dict[str, Any], params: dict[str, str] | None = None) -> WriteFileStep:
    content = data.get("content", "")
    if params is not None and content:
        content = strict_substitute(content, params, f"step.{data.get('id', 'write-file')}.content")

    return WriteFileStep(
        id=data.get("id", "write-file"),
        path=data["path"],
        content=content,
        create_parents=data.get("create_parents", True),
        registry=data.get("registry"),
        recipe_id=data.get("recipe_id"),
    )


def _build_managed_block(data: dict[str, Any], params: dict[str, str] | None = None) -> ManagedBlockStep:
    content = data.get("content", "")
    if params is not None and content:
        content = strict_substitute(content, params, f"step.{data.get('id', 'managed-block')}.content")

    return ManagedBlockStep(
        id=data.get("id", "managed-block"),
        path=data["path"],
        block_id=data["block_id"],
        content=content,
        registry=data.get("registry"),
        recipe_id=data.get("recipe_id"),
        comment_prefix=data.get("comment_prefix", "#"),
    )


_builders: dict[str, Callable[[dict[str, Any]], Any]] = {}
for _t, _b in {
    "shell": _build_shell,
    "callable": _build_callable,
    "sequence": _build_sequence,
    "confirm": _build_confirm,
    "select": _build_select,
    "conditional": _build_conditional,
    "config-set": _build_config_set,
    "write-file": _build_write_file,
    "managed-block": _build_managed_block,
}.items():
    _builders[_t] = _b


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_step_type(type_name: str, constructor: Callable[[dict[str, Any]], Any]) -> None:
    """Register a step type for the factory. Raises on duplicate."""
    if type_name in _builders:
        raise _step_error(1, f"duplicate step type {type_name!r}")
    _builders[type_name] = constructor
    _REGISTRY.register(type_name, constructor)


_PARAMS_ACCEPTING_TYPES = frozenset({
    "shell", "sequence", "select", "conditional",
    "config-set", "write-file", "managed-block",
})


def build_step(data: dict[str, Any], params: dict[str, str] | None = None) -> Any:
    """Build a step from a declarative spec dict via the step registry.

    The ``type`` field selects only a registered constructor.  Unknown type
    raises with VAL-STEP error code.

    Args:
        data: Step definition dict with at least a ``type`` key.
        params: Optional placeholder mapping for strict build-time substitution.
            When provided, ``{KEY}`` patterns are validated against this dict
            and replaced before constructing the step (raises on unknown keys).
    """
    step_type = data.get("type")
    if not step_type:
        raise _step_error(1, "step definition missing 'type' field")

    builder = _builders.get(step_type)
    if builder is None:
        registered = sorted(_builders.keys())
        raise _step_error(1, f"unknown step type {step_type!r}; registered: {registered}")

    if params is not None and step_type in _PARAMS_ACCEPTING_TYPES:
        return builder(data, params)  # type: ignore[call-arg]
    return builder(data)


def build_steps_from_defs(
    step_defs: list[dict[str, Any]],
    params: dict[str, str],
    *,
    recipe_id: str | None = None,
    registry: Any | None = None,
) -> list[Any]:
    """Build a list of steps from YAML step definitions with strict substitution.

    Steps without an explicit ``id`` are assigned ``step-<index>``.  All
    string values are subject to strict build-time placeholder substitution
    against *params*; unknown keys raise.

    Args:
        step_defs: List of step definition dicts (each with a ``type`` key).
        params: Placeholder mapping for ``{KEY}`` substitution.
        recipe_id: Optional recipe identifier for artifact registry association.
        registry: Optional artifact registry for ownership tracking.
    """
    steps = []
    for i, defn in enumerate(step_defs):
        step_data = dict(defn)
        if "id" not in step_data:
            step_data["id"] = f"step-{i}"
        # Inject registry/recipe_id into structured step data
        if recipe_id is not None or registry is not None:
            step_data.setdefault("recipe_id", recipe_id)
            step_data.setdefault("registry", registry)
        steps.append(build_step(step_data, params=params))
    return steps


def registered_types() -> list[str]:
    """Return the sorted list of registered step types."""
    return sorted(_builders.keys())


# Ensure builtins are registered at import time
_register_builtins()
