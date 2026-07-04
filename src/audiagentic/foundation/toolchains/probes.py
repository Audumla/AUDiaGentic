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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import make_error

from .config_reader import UNSET, read_config_value


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
]
