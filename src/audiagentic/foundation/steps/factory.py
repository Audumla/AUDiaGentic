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
from .structured import (
    ConfigRemoveStep,
    ConfigSetStep,
    DownloadStep,
    ManagedBlockStep,
    WriteFileStep,
)

logger = logging.getLogger(__name__)

_step_error = make_error_factory("VAL", "STEP", "step-factory")
_sub_error = make_error_factory("VAL", "STUB", "step-substitution")

StepConstructor = Callable[..., Any]


class StepFactory(Protocol):
    """Typed step factory protocol."""

    def build(self, data: dict[str, Any]) -> Any: ...

    def registered_types(self) -> list[str]: ...


# Per-type JSON-schema fragments, co-located with each step's builder. The recipe
# loader validates a step against the fragment its `type` registers — so there is
# no central hard-coded list of step types anywhere. Foundation registers its
# builtins here; other layers (e.g. providers) register their own via
# register_step_type(..., schema=...), keeping this module domain-neutral.
_step_schemas: dict[str, dict[str, Any]] = {}

# Reusable envelope for a nested step inside a composite (sequence/select/
# conditional). The loader recurses into those to validate each child against its
# own registered fragment, so here we only assert the common shape.
_NESTED_STEP = {"type": "object", "required": ["type", "id"], "properties": {
    "type": {"type": "string", "minLength": 1}, "id": {"type": "string", "minLength": 1},
}}


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

# Schema fragment per builtin step type, co-located with the builders above.
# `id` and `type` are common to every step; each fragment adds its own fields.
_KEY_PATH = {"oneOf": [
    {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
    {"type": "string", "minLength": 1},
]}
_ID = {"type": "string", "minLength": 1}
_BUILTIN_STEP_SCHEMAS: dict[str, dict[str, Any]] = {
    "shell": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "command"], "properties": {
            "type": {"const": "shell"}, "id": _ID,
            "command": {"oneOf": [{"type": "string", "minLength": 1},
                {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}]},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 600},
            "dry-run": {"type": "boolean"}, "cwd": {"type": "string", "minLength": 1},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            "platform": {"type": "object"},
            "compensate-command": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "shell": {"type": "boolean"}}},
    "callable": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "fn"], "properties": {
            "type": {"const": "callable"}, "id": _ID, "fn": {"type": "string", "minLength": 1},
            "dry-run": {"type": "boolean"}}},
    "sequence": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "steps"], "properties": {
            "type": {"const": "sequence"}, "id": _ID,
            "steps": {"type": "array", "items": _NESTED_STEP, "minItems": 1},
            "fail-fast": {"type": "boolean"}, "compensate-on-failure": {"type": "boolean"}}},
    "confirm": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "prompt"], "properties": {
            "type": {"const": "confirm"}, "id": _ID, "prompt": {"type": "string", "minLength": 1},
            "default": {"type": "string"}}},
    "select": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "select", "variants"], "properties": {
            "type": {"const": "select"}, "id": _ID, "select": {"type": "string", "minLength": 1},
            "variants": {"type": "object", "additionalProperties": _NESTED_STEP},
            "fallback": {"type": "string", "minLength": 1}}},
    "conditional": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "condition-key", "when-true"], "properties": {
            "type": {"const": "conditional"}, "id": _ID, "condition-key": {"type": "string", "minLength": 1},
            "when-true": _NESTED_STEP, "when-false": _NESTED_STEP}},
    "config-set": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "path", "key-path", "value"], "properties": {
            "type": {"const": "config-set"}, "id": _ID, "path": {"type": "string", "minLength": 1},
            "key-path": _KEY_PATH, "value": True}},
    "config-remove": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "path", "key-path"], "properties": {
            "type": {"const": "config-remove"}, "id": _ID, "path": {"type": "string", "minLength": 1},
            "key-path": _KEY_PATH}},
    "write-file": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "path"], "properties": {
            "type": {"const": "write-file"}, "id": _ID, "path": {"type": "string", "minLength": 1},
            "content": {"type": "string"}, "create-parents": {"type": "boolean"}}},
    "download": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "base-url", "dest-dir", "files"], "properties": {
            "type": {"const": "download"}, "id": _ID, "base-url": {"type": "string", "minLength": 1},
            "dest-dir": {"type": "string", "minLength": 1},
            "files": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "optional-files": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 600}}},
    "managed-block": {"type": "object", "additionalProperties": False,
        "required": ["type", "id", "path", "block-id"], "properties": {
            "type": {"const": "managed-block"}, "id": _ID, "path": {"type": "string", "minLength": 1},
            "block-id": {"type": "string", "minLength": 1}, "content": {"type": "string"},
            "comment-prefix": {"type": "string"}}},
}


def _register_builtins() -> None:
    """Register built-in step types idempotently."""
    _REGISTRY.register("shell", _build_shell)
    _REGISTRY.register("callable", _build_callable)
    _REGISTRY.register("sequence", _build_sequence)
    _REGISTRY.register("confirm", _build_confirm)
    _REGISTRY.register("select", _build_select)
    _REGISTRY.register("conditional", _build_conditional)
    _REGISTRY.register("config-set", _build_config_set)
    _REGISTRY.register("config-remove", _build_config_remove)
    _REGISTRY.register("write-file", _build_write_file)
    _REGISTRY.register("download", _build_download)
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


def _build_config_remove(data: dict[str, Any], params: dict[str, str] | None = None) -> ConfigRemoveStep:
    kp = data.get("key_path")
    if isinstance(kp, str):
        key_path = tuple(kp.split("."))
    elif kp is not None:
        key_path = tuple(kp)
    else:
        raise _step_error(1, "config-remove step missing 'key_path'")

    path = data["path"]
    if params is not None:
        path = strict_substitute(path, params, f"step.{data.get('id', 'config-remove')}.path")
        key_path = tuple(
            strict_substitute(seg, params, f"step.{data.get('id', 'config-remove')}.key_path")
            for seg in key_path
        )

    return ConfigRemoveStep(
        id=data.get("id", "config-remove"),
        path=path,
        key_path=key_path,
        registry=data.get("registry"),
        recipe_id=data.get("recipe_id"),
    )


def _build_download(data: dict[str, Any], params: dict[str, str] | None = None) -> DownloadStep:
    base_url = data["base_url"]
    dest_dir = data["dest_dir"]
    files = list(data.get("files", []))
    optional_files = list(data.get("optional_files", []))

    if params is not None:
        base_url = strict_substitute(base_url, params, f"step.{data.get('id', 'download')}.base_url")
        dest_dir = strict_substitute(dest_dir, params, f"step.{data.get('id', 'download')}.dest_dir")
        files = [strict_substitute(f, params, f"step.{data.get('id', 'download')}.files") for f in files]
        optional_files = [
            strict_substitute(f, params, f"step.{data.get('id', 'download')}.optional_files")
            for f in optional_files
        ]

    return DownloadStep(
        id=data.get("id", "download"),
        base_url=base_url,
        files=tuple(files),
        dest_dir=dest_dir,
        optional_files=tuple(optional_files),
        timeout=data.get("timeout", 30),
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
    "config-remove": _build_config_remove,
    "write-file": _build_write_file,
    "download": _build_download,
    "managed-block": _build_managed_block,
}.items():
    _builders[_t] = _b

_step_schemas.update(_BUILTIN_STEP_SCHEMAS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_step_type(
    type_name: str,
    constructor: Callable[[dict[str, Any]], Any],
    *,
    schema: dict[str, Any] | None = None,
    accepts_params: bool = False,
) -> None:
    """Register a step type for the factory. Raises on duplicate.

    ``schema`` is the JSON-schema fragment for this step's fields, used by the
    recipe loader to validate the step (no central hard-coded type list). Set
    ``accepts_params=True`` when the builder takes a ``params`` mapping for
    build-time ``{KEY}`` substitution.
    """
    if type_name in _builders:
        raise _step_error(1, f"duplicate step type {type_name!r}")
    _builders[type_name] = constructor
    _REGISTRY.register(type_name, constructor)
    if schema is not None:
        _step_schemas[type_name] = schema
    if accepts_params:
        _params_accepting_types.add(type_name)


def step_schema(type_name: str) -> dict[str, Any] | None:
    """Return the registered JSON-schema fragment for a step type, or None."""
    return _step_schemas.get(type_name)


_params_accepting_types: set[str] = {
    "shell", "sequence", "select", "conditional",
    "config-set", "config-remove", "write-file", "download", "managed-block",
}


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

    if params is not None and step_type in _params_accepting_types:
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
