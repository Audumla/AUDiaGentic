"""Workflow step builder for declarative YAML specs.

Builds step instances from declarative step specifications using the canonical
foundation.steps types.  Uses a dispatch table — no if/elif chains on step type.
"""
from __future__ import annotations

from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.steps import (
    CallableStep,
    ConditionalStep,
    ConfirmStep,
    PlatformOverrides,
    SelectStep,
    SequenceStep,
    ShellStep,
)


def _build_shell_step(spec: dict[str, Any]) -> ShellStep:
    command = spec.get("command")
    if not command:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Shell step missing required field 'command'",
        )
    cmd = tuple(command) if isinstance(command, list) else command
    platform = None
    if "platform" in spec:
        p = spec["platform"]
        platform = PlatformOverrides(
            win=tuple(p["win"]) if isinstance(p.get("win"), list) else p.get("win"),
            darwin=tuple(p["darwin"]) if isinstance(p.get("darwin"), list) else p.get("darwin"),
            linux=tuple(p["linux"]) if isinstance(p.get("linux"), list) else p.get("linux"),
        )
    return ShellStep(
        id=spec.get("id", "shell"),
        command=cmd,
        timeout=spec.get("timeout", 300),
        dry_run=spec.get("dry_run", False),
        cwd=spec.get("cwd"),
        env=spec.get("env"),
        platform=platform,
    )


def _build_callable_step(spec: dict[str, Any]) -> CallableStep:
    from audiagentic.foundation.config.refs import resolve_ref

    fn_ref = spec.get("fn")
    if not fn_ref:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Callable step missing required field 'fn'",
        )
    fn = resolve_ref(fn_ref)
    return CallableStep(
        id=spec.get("id", "callable"),
        fn=fn,
        dry_run=spec.get("dry_run", False),
    )


def _build_sequence_step(spec: dict[str, Any]) -> SequenceStep:
    steps_spec = spec.get("steps", [])
    steps = tuple(build_step_from_spec(s) for s in steps_spec)
    return SequenceStep(
        id=spec.get("id", "sequence"),
        steps=steps,
        fail_fast=spec.get("fail_fast", True),
        compensate_on_failure=False,
    )


def _build_select_step(spec: dict[str, Any]) -> SelectStep:
    from audiagentic.foundation.config.refs import resolve_ref

    select_ref = spec.get("select")
    if not select_ref:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Select step missing required field 'select'",
        )
    select_fn = resolve_ref(select_ref)
    fallback_ref = spec.get("fallback")
    return SelectStep(
        id=spec.get("id", "select"),
        select=select_fn,
        variants={k: build_step_from_spec(v) for k, v in spec.get("variants", {}).items()},
        fallback=resolve_ref(fallback_ref) if fallback_ref else None,
    )


def _build_confirm_step(spec: dict[str, Any]) -> ConfirmStep:
    prompt = spec.get("prompt")
    if not prompt:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Confirm step missing required field 'prompt'",
        )
    return ConfirmStep(
        id=spec.get("id", "confirm"),
        prompt=prompt,
        default=spec.get("default", "yes"),
    )


def _build_conditional_step(spec: dict[str, Any]) -> ConditionalStep:
    key = spec.get("condition_key")
    if not key:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Conditional step missing required field 'condition_key'",
        )
    when_true = build_step_from_spec(spec["when_true"])
    when_false = None
    if "when_false" in spec:
        when_false = build_step_from_spec(spec["when_false"])
    return ConditionalStep(
        id=spec.get("id", "conditional"),
        condition_key=key,
        when_true=when_true,
        when_false=when_false,
    )


_STEP_BUILDERS: dict[str, Any] = {
    "shell": _build_shell_step,
    "callable": _build_callable_step,
    "sequence": _build_sequence_step,
    "select": _build_select_step,
    "confirm": _build_confirm_step,
    "conditional": _build_conditional_step,
}


def build_step_from_spec(spec: dict[str, Any]) -> Any:
    step_type = spec.get("type")
    if not step_type:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message="Step spec missing required field 'type'",
        )
    builder = _STEP_BUILDERS.get(step_type)
    if not builder:
        raise AudiaGenticError(
            code="VAL-DESC-002",
            kind="descriptor",
            message=f"Unknown step type {step_type!r}; valid: {sorted(_STEP_BUILDERS)}",
        )
    return builder(spec)
