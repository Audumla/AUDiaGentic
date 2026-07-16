"""Status-check primitives for provisioning recipes.

Small, composable checks a recipe uses to answer "is this already installed and
configured?" — a command probe, a file-exists check, a config-key check, and an
AND/OR composite. Each returns a structured :class:`ProbeResult` with a
pass/fail flag and a human-readable diagnostic, never a bare bool.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import make_error, make_error_factory
from audiagentic.foundation.logging.redaction import redact_text

from .config_reader import UNSET, read_config_value

_probe_error: Any = make_error_factory("VAL", "DEP", "component-dependencies")


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a status check, with optional nested results for composites."""

    passed: bool
    detail: str = ""
    sub_results: tuple[ProbeResult, ...] = field(default_factory=tuple)


class Probe(Protocol):
    """Anything that can report a pass/fail status."""

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult: ...


def _expand(path: str | Path) -> Path:
    return Path(str(path)).expanduser()


_SHELL_METACHARS = ("|", "&&", ";", ">", "<")


def safe_command_parts(command: str) -> list[str]:
    """Return argv for a simple command, refusing shell compound syntax.

    Security guard for commands sourced from config/matrix data: compound
    shell operators are rejected (VAL-CMD-001) rather than passed to a shell.
    """
    if any(token in command for token in _SHELL_METACHARS):
        raise make_error(
            prefix="VAL",
            component="CMD",
            number=1,
            kind="validation",
            message=(
                f"shell compound command requires structured shell-step support: {command!r}"
            ),
        )
    import shlex

    return shlex.split(command)


@dataclass(frozen=True)
class CommandProbe:
    """Run a command and check its exit code and/or stdout against a pattern."""

    command: tuple[str, ...]
    expect_exit: int | None = 0
    output_pattern: str | None = None
    timeout: int = 30

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult:
        exe = self.command[0]
        if shutil.which(exe) is None:
            return ProbeResult(False, f"{exe} not on PATH")
        try:
            proc = subprocess.run(  # noqa: S603 - command is recipe-controlled, not user input
                list(self.command),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(False, f"timed out after {self.timeout}s")
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(False, str(exc))

        if self.expect_exit is not None and proc.returncode != self.expect_exit:
            return ProbeResult(
                False, f"exit {proc.returncode} (expected {self.expect_exit})"
            )
        output = (proc.stdout or "") + (proc.stderr or "")
        if self.output_pattern is not None and not re.search(self.output_pattern, output):
            return ProbeResult(False, f"output did not match {self.output_pattern!r}")
        return ProbeResult(True, f"{exe} ok")


@dataclass(frozen=True)
class FileExistsCheck:
    """Verify a path exists, optionally matching a content regex."""

    path: str | Path
    content_pattern: str | None = None

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult:
        target = _expand(self.path)
        if not target.exists():
            return ProbeResult(False, f"missing: {target}")
        if self.content_pattern is not None:
            try:
                text = target.read_text(encoding="utf-8")
            except OSError as exc:
                return ProbeResult(False, f"unreadable: {exc}")
            if not re.search(self.content_pattern, text):
                return ProbeResult(False, f"{target} lacks {self.content_pattern!r}")
        return ProbeResult(True, f"present: {target}")


@dataclass(frozen=True)
class ConfigKeyCheck:
    """Verify a key path exists in a TOML/JSON/YAML file, optionally with a value."""

    path: str | Path
    key_path: tuple[str, ...]
    expected_value: Any = UNSET

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult:
        target = _expand(self.path)
        if not target.exists():
            return ProbeResult(False, f"config missing: {target}")
        dotted = ".".join(self.key_path)
        try:
            value = read_config_value(target, self.key_path)
        except Exception as exc:  # noqa: BLE001 - malformed config is a failed probe
            return ProbeResult(False, f"unreadable config {target}: {exc}")
        if value is UNSET:
            return ProbeResult(False, f"key absent: {dotted}")
        if self.expected_value is not UNSET and value != self.expected_value:
            return ProbeResult(
                False, f"{dotted}={value!r} (expected {self.expected_value!r})"
            )
        return ProbeResult(True, f"key present: {dotted}")


@dataclass(frozen=True)
class CompositeHealthCheck:
    """Compose sub-checks with AND / OR / at-least-N semantics (RV03).

    - ``mode="and"`` — all must pass (short-circuits on first failure).
    - ``mode="or"`` — any may pass (short-circuits on first success).
    - ``mode="atleast"`` — at least ``threshold`` must pass.
    """

    checks: tuple[Probe, ...]
    mode: str = "and"  # "and" | "or" | "atleast"
    threshold: int = 1

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult:
        if self.mode not in {"and", "or", "atleast"}:
            raise make_error(
                prefix="VAL", component="PROBE", number=1, kind="toolchains",
                message=f"mode must be 'and', 'or', or 'atleast', got {self.mode!r}",
                details={"mode": self.mode},
            )
        results: list[ProbeResult] = []
        passed = 0
        for probe in self.checks:
            result = probe.check(context)
            results.append(result)
            if result.passed:
                passed += 1
            if self.mode == "and" and not result.passed:
                return ProbeResult(False, f"failed: {result.detail}", tuple(results))
            if self.mode == "or" and result.passed:
                return ProbeResult(True, f"passed: {result.detail}", tuple(results))
            if self.mode == "atleast" and passed >= self.threshold:
                return ProbeResult(
                    True, f"{passed}/{self.threshold} checks passed", tuple(results)
                )
        if self.mode == "and":
            return ProbeResult(True, "all checks passed", tuple(results))
        if self.mode == "or":
            return ProbeResult(False, "no check passed", tuple(results))
        return ProbeResult(
            False, f"only {passed}/{self.threshold} checks passed", tuple(results)
        )


@dataclass(frozen=True)
class _PredicateProbe:
    """Adapt a zero-argument bool callable to the :class:`Probe` protocol."""

    predicate: Callable[[], bool]
    label: str

    def check(self, context: dict[str, Any] | None = None) -> ProbeResult:
        try:
            passed = bool(self.predicate())
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(False, redact_text(str(exc)))
        return ProbeResult(passed, f"{self.label} {'ok' if passed else 'not available'}")


def _spec_payload(spec: str, prefix: str) -> str:
    payload = spec[len(prefix):].strip()
    if not payload:
        raise _probe_error(1, f"empty probe payload: {spec!r}", probe=spec)
    return payload


def probe_from_spec(spec: str) -> Probe:
    """Build a :class:`Probe` from a declarative ``probe:`` spec string.

    The single production parser for dependency probe syntax. Supported forms:
    ``binary:<name>``, ``all-binaries:<a,b>``, ``path:<path>``,
    ``command:<argv>``, ``custom:<module>:<dotpath>``, and exact ``toolchain:uv``.
    Unknown or malformed syntax raises the canonical VAL-DEP-001 error.
    """
    from .detect import tool_available, uv_available

    if spec == "toolchain:uv":
        return _PredicateProbe(uv_available, "uv")

    if spec.startswith("binary:"):
        binary = _spec_payload(spec, "binary:")
        return _PredicateProbe(lambda: tool_available(binary), binary)

    if spec.startswith("all-binaries:"):
        payload = _spec_payload(spec, "all-binaries:")
        binaries = tuple(part.strip() for part in payload.split(",") if part.strip())
        if not binaries:
            raise _probe_error(1, f"empty probe payload: {spec!r}", probe=spec)
        return _PredicateProbe(
            lambda: all(tool_available(binary) for binary in binaries),
            ",".join(binaries),
        )

    if spec.startswith("path:"):
        return FileExistsCheck(_spec_payload(spec, "path:"))

    if spec.startswith("command:"):
        payload = _spec_payload(spec, "command:")
        argv = tuple(safe_command_parts(payload))
        if not argv:
            raise _probe_error(1, f"empty probe payload: {spec!r}", probe=spec)
        return CommandProbe(command=argv, timeout=10)

    if spec.startswith("custom:"):
        from audiagentic.foundation.refs import resolve_ref

        ref = _spec_payload(spec, "custom:")
        try:
            predicate = resolve_ref(ref)
        except Exception as exc:  # noqa: BLE001
            raise _probe_error(
                1, f"unresolvable custom probe ref: {ref!r}", probe=spec
            ) from exc
        if not callable(predicate):
            raise _probe_error(
                1, f"custom probe ref is not callable: {ref!r}", probe=spec
            )
        return _PredicateProbe(predicate, ref)

    raise _probe_error(1, f"unknown probe syntax: {spec!r}", probe=spec)


def check_with_retry(
    probe: Probe,
    *,
    retries: int = 0,
    delay_seconds: float = 0.0,
    context: dict[str, Any] | None = None,
) -> ProbeResult:
    """Run ``probe`` up to ``retries + 1`` times until it passes (RV06).

    Lets verify hooks tolerate slow systems with a configurable retry budget.
    Probes are side-effect-free, so re-running is safe.
    """
    attempt = 0
    result = probe.check(context)
    while not result.passed and attempt < retries:
        attempt += 1
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        result = probe.check(context)
    suffix = "" if attempt == 0 else f" (after {attempt} retr{'y' if attempt == 1 else 'ies'})"
    return ProbeResult(result.passed, f"{result.detail}{suffix}", result.sub_results)


__all__ = [
    "CommandProbe",
    "CompositeHealthCheck",
    "ConfigKeyCheck",
    "FileExistsCheck",
    "Probe",
    "ProbeResult",
    "check_with_retry",
    "probe_from_spec",
    "safe_command_parts",
]
