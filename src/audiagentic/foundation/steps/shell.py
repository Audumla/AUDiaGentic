"""Canonical subprocess step with platform resolution and redacted outcomes."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.logging.redaction import redact_text, truncate_output
from audiagentic.runtime.system.platform import platform_key as _platform_key

from .results import StepResult


@dataclass(frozen=True)
class PlatformOverrides:
    win: tuple[str, ...] | None = None
    darwin: tuple[str, ...] | None = None
    linux: tuple[str, ...] | None = None

    def resolve(self, platform_key: str | None = None) -> tuple[str, ...] | None:
        return {"win": self.win, "darwin": self.darwin, "linux": self.linux}.get(platform_key or _platform_key())


@dataclass(frozen=True)
class ShellStep:
    id: str
    command: tuple[str, ...]
    timeout: int = 300
    dry_run: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    progress_callback: Any | None = None
    platform: PlatformOverrides | None = None
    compensate_command: tuple[str, ...] | None = None
    shell: bool = False

    def plan(self, context: dict[str, Any]) -> StepResult:
        command = list(self._render_command(context))
        return StepResult(status="planned", outputs={"command": command}, command_plan=[command])

    def run(self, context: dict[str, Any]) -> StepResult:
        if self.dry_run:
            return self.plan(context)
        cmd = self._render_command(context)
        if self.shell:
            return self._run_shell(" ".join(cmd), context)
        return self._execute(cmd, context)

    def compensate(self, context: dict[str, Any]) -> StepResult:
        if self.compensate_command is None:
            return StepResult(status="skipped", reason="no compensation declared")
        cmd = self._render(self.compensate_command, context)
        if self.shell:
            return self._run_shell(" ".join(cmd), context)
        return self._execute(cmd, context)

    def _execute(self, command: tuple[str, ...], context: dict[str, Any]) -> StepResult:
        executable = shutil.which(command[0])
        if executable is None:
            return StepResult(status="failed", outputs={"command": list(command)}, reason=f"{command[0]} is not available on PATH")
        resolved = (executable, *command[1:])
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        if self.env:
            env.update(self.env)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(resolved),
                cwd=os.path.expanduser(self.cwd) if self.cwd else context.get("cwd"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            lines: list[str] = []
            if self.progress_callback:
                def _stream() -> None:
                    assert process and process.stdout
                    for line in process.stdout:
                        safe = redact_text(line.rstrip("\n\r"))
                        lines.append(safe)
                        self.progress_callback(safe)  # type: ignore[misc]
                reader = threading.Thread(target=_stream, daemon=True)
                reader.start()
                process.wait(timeout=self.timeout)
                reader.join(timeout=1)
            else:
                output, _ = process.communicate(timeout=self.timeout)
                lines = [redact_text(line) for line in output.splitlines()]
        except subprocess.TimeoutExpired:
            if process:
                process.kill()
                process.wait(timeout=5)
            return StepResult(status="failed", outputs={"command": list(resolved)}, reason=f"timed out after {self.timeout}s")
        except Exception as exc:  # noqa: BLE001
            return StepResult(status="failed", outputs={"command": list(resolved)}, reason=redact_text(str(exc)))
        output = truncate_output("\n".join(lines))
        return StepResult(
            status="ok" if process.returncode == 0 else "failed",
            outputs={"command": list(resolved), "returncode": process.returncode, "stdout": output, "stderr": ""},
            reason=None if process.returncode == 0 else output or None,
        )

    def _run_shell(self, cmd: str, context: dict[str, Any]) -> StepResult:
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        if self.env:
            env.update(self.env)
        try:
            proc = subprocess.run(
                cmd,
                cwd=os.path.expanduser(self.cwd) if self.cwd else context.get("cwd"),
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
                outputs={"command": cmd, "returncode": proc.returncode, "stdout": safe_stdout},
                reason=None if proc.returncode == 0 else redact_text(proc.stdout.strip()) or None,
            )
        except subprocess.TimeoutExpired:
            return StepResult(status="failed", outputs={"command": cmd}, reason=f"timed out after {self.timeout}s")
        except Exception as exc:  # noqa: BLE001
            return StepResult(status="failed", outputs={"command": cmd}, reason=redact_text(str(exc)))

    def _render_command(self, context: dict[str, Any]) -> tuple[str, ...]:
        base = self.platform.resolve() if self.platform else None
        return self._render(base or self.command, context)

    @staticmethod
    def _render(command: tuple[str, ...], context: dict[str, Any]) -> tuple[str, ...]:
        return tuple(part.format(**context) for part in command)
