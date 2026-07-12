"""Shell command provisioning step.

Deliberately separate from ``workflow.invocation.steps.ShellStep`` (SL09):
this step carries revert commands, shell-mode strings, and compensation
semantics; the workflow step carries streaming progress and the
answers/question protocol. See the SL09 review for the won't-merge rationale.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

from audiagentic.foundation.logging.redaction import redact_text, truncate_output
from audiagentic.foundation.workflow.invocation.models import StepResult

from ..artifact_registry import ArtifactRegistry
from .base import _substitute, register_step_type


class ShellProvisionStep:
    """Execute a shell command with optional explicit revert."""

    def __init__(
        self,
        id: str,
        command: list[str] | str,
        *,
        revert_command: list[str] | str | None = None,
        shell: bool = False,
        timeout: int = 300,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.id = id
        self.command: list[str] | str = command
        self.revert_command: list[str] | str | None = revert_command
        self.shell = shell
        self.timeout = timeout
        self.cwd = cwd
        self.env = env

    def _execute(
        self, cmd: list[str] | str, *, shell_mode: bool
    ) -> StepResult:
        if shell_mode:
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
            return self._run_shell(cmd_str)
        return self._run_argv(cmd if isinstance(cmd, list) else [cmd])

    def _run_argv(self, cmd: list[str]) -> StepResult:
        import shutil as _shutil

        # Drop --flag= args where the value is empty (optional substitution params
        # like --bank-id= when bank_id is unset). cmd[0] is never a flag so this
        # is safe to apply to the whole list.
        cmd = [a for a in cmd if not (a.startswith("--") and a.endswith("="))]

        manager = cmd[0]
        resolved = _shutil.which(manager)
        if resolved is None:
            return StepResult(
                status="failed",
                outputs={"command": list(cmd)},
                reason=f"{manager} is not available on PATH",
            )

        command = [resolved, *cmd[1:]]
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.env:
            env.update(self.env)
        cwd = os.path.expanduser(self.cwd) if self.cwd else None

        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
            )
            raw_stdout = redact_text(proc.stdout.rstrip("\n"))
            safe_stdout = truncate_output(raw_stdout)
            return StepResult(
                status="ok" if proc.returncode == 0 else "failed",
                outputs={
                    "command": command,
                    "returncode": proc.returncode,
                    "stdout": safe_stdout,
                },
                reason=None if proc.returncode == 0 else redact_text(proc.stdout.strip()) or None,
            )
        except subprocess.TimeoutExpired:
            return StepResult(
                status="failed",
                outputs={"command": command},
                reason=f"timed out after {self.timeout}s",
            )
        except Exception as exc:
            return StepResult(
                status="failed",
                outputs={"command": command},
                reason=str(exc),
            )

    def _run_shell(self, cmd: str) -> StepResult:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.env:
            env.update(self.env)
        cwd = os.path.expanduser(self.cwd) if self.cwd else None

        if not isinstance(cmd, str):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = cmd

        try:
            proc = subprocess.run(
                cmd_str,
                cwd=cwd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=env,
            )
            raw_stdout = redact_text(proc.stdout.rstrip("\n"))
            safe_stdout = truncate_output(raw_stdout)
            return StepResult(
                status="ok" if proc.returncode == 0 else "failed",
                outputs={
                    "command": cmd_str,
                    "returncode": proc.returncode,
                    "stdout": safe_stdout,
                },
                reason=None if proc.returncode == 0 else redact_text(proc.stdout.strip()) or None,
            )
        except subprocess.TimeoutExpired:
            return StepResult(
                status="failed",
                outputs={"command": cmd_str},
                reason=f"timed out after {self.timeout}s",
            )
        except Exception as exc:
            return StepResult(
                status="failed",
                outputs={"command": cmd_str},
                reason=str(exc),
            )

    def run(self, context: dict[str, Any]) -> StepResult:
        cmd = self._render(self.command, context)
        return self._execute(cmd, shell_mode=self.shell)

    def revert(self, context: dict[str, Any]) -> StepResult:
        if self.revert_command is None:
            return StepResult(
                status="skipped", reason="no revert declared"
            )
        cmd = self._render(self.revert_command, context)
        return self._execute(cmd, shell_mode=self.shell)

    def dry_run(self, context: dict[str, Any]) -> StepResult:
        cmd = self._render(self.command, context)
        return StepResult(
            status="planned",
            outputs={
                "command": cmd if isinstance(cmd, list) else str(cmd),
                "shell": self.shell,
            },
        )

    def _render(self, value: list[str] | str, context: dict[str, Any]) -> list[str] | str:
        """Two-stage template substitution — only ShellProvisionStep uses this pattern.

        Stage 1 (factory time): ``_substitute()`` in ``_shell_from_dict`` resolves
        ``{PARAM}`` placeholders from the recipe's params dict. This is strict:
        unknown keys raise at YAML-parse / factory time so bad recipes fail fast.

        Stage 2 (run time): ``str.format(**context)`` here resolves ``{context_key}``
        values only known when the step executes. Python's built-in format is
        lenient — missing keys produce ``KeyError``, but the template surface is
        narrow (runtime values from the invocation context, not recipe author input).

        This two-stage design separates concerns: params known at recipe-build time
        vs context keys only known at run time. Per Std §3, no shared render helper
        is extracted because ShellProvisionStep is the sole consumer of runtime
        str.format substitution (RS13 characterization confirmed single-consumer).
        """
        if isinstance(value, list):
            return [part.format(**context) for part in value]
        return value.format(**context)


def _shell_from_dict(
    data: dict[str, Any],
    params: dict[str, str],
    registry: ArtifactRegistry | None,
    recipe_id: str | None,
) -> ShellProvisionStep:
    step_id = data.get("id", "shell-anonymous")
    raw_cmd = data["command"]
    command = _substitute(raw_cmd, params, f"step.{step_id}.command")
    revert_command = data.get("revert_command")
    if revert_command is not None:
        revert_command = _substitute(revert_command, params, f"step.{step_id}.revert_command")
    cwd = data.get("cwd")
    if cwd is not None:
        cwd = _substitute(cwd, params, f"step.{step_id}.cwd")
    env = data.get("env")
    if env is not None:
        env = _substitute(env, params, f"step.{step_id}.env")
    return ShellProvisionStep(
        id=step_id,
        command=command,
        revert_command=revert_command,
        shell=data.get("shell", False),
        timeout=data.get("timeout", 300),
        cwd=cwd,
        env=env,
    )


register_step_type("shell", _shell_from_dict)
