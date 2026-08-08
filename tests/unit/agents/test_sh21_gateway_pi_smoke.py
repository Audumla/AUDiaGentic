"""SH21 validation: gateway-managed Pi smoke with fake executable.

Exercises the full gateway worker/provider dispatch (NOT directly calling the
Pi adapter) to prove that a multiline request reaches the Pi custom execution
adapter through stdin:

  1. The spawned command is ``pi --print`` with NO prompt argument.
  2. The full multiline input is supplied via stdin with newlines intact.
  3. Public request output/error remains redacted.

A controllable fake Pi executable records argv and stdin to temporary files so
the test can inspect exactly what the child process received. No live model
is involved.

Run: python -m pytest tests/unit/agents/test_sh21_gateway_pi_smoke.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# ── Multiline prompt with code fences (SH21 reproduction shape) ───────────

MULTILINE_PROMPT = (
    "Implement the following:\n"
    "\n"
    "```python\n"
    "def calculate(x: int, y: int) -> int:\n"
    "    return x + y\n"
    "```\n"
    "\n"
    "Return a brief summary."
)


# ── Test fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_pi_dir(tmp_path: Path) -> Path:
    """Create a directory that will hold the fake Pi executable."""
    d = tmp_path / "fake_pi_bin"
    d.mkdir()
    return d


@pytest.fixture
def recording_dir(tmp_path: Path) -> Path:
    """Create a directory for recording files (argv, stdin)."""
    d = tmp_path / "pi_recording"
    d.mkdir()
    return d


@pytest.fixture
def fake_pi_setup(
    fake_pi_dir: Path,
    recording_dir: Path,
) -> tuple[Path, Path]:
    """Create the fake Pi executable that records argv and stdin.

    On Windows the worker subprocess resolves commands via ``shutil.which``
    which uses PATHEXT (.cmd/.bat/.exe).  A bare ``pi`` script has no
    PATHEXT extension so it is invisible to command resolution.  We create
    both a Unix-style ``pi`` shebang script **and** a Windows ``pi.cmd``
    batch wrapper so ``shutil.which("pi")`` succeeds on every platform.

    The fake Pi writes its argv and stdin to fixed paths under recording_dir
    (not via env vars — those aren't passed through the worker environment).
    Returns (exe_path, recording_dir) so the test can inspect recordings.
    """
    # Shared Python recorder script (extensionless on Unix, .py on Windows)
    # Use forward-slash POSIX path so backslashes don't become escape sequences
    # in the generated Python source (e.g. "\U" → SyntaxError on Windows).
    recording_dir_posix = recording_dir.as_posix()
    recorder_py = fake_pi_dir / "_pi_recorder.py"
    recorder_py.write_text(f"""import json, os, sys

recording_dir = "{recording_dir_posix}"

def main():
    argv_file = os.path.join(recording_dir, "test_argv.json")
    stdin_file = os.path.join(recording_dir, "test_stdin.txt")

    # Write argv to the recording file
    with open(argv_file, "w") as f:
        json.dump(sys.argv, f)

    # Read all of stdin and write it out
    data = sys.stdin.read() if not sys.stdin.isatty() else ""
    with open(stdin_file, "w") as f:
        f.write(data)

    # Write parseable response for the pi-plaintext extractor
    print("OK")

if __name__ == "__main__":
    main()
""")

    # Unix-style shebang script — works on Linux/macOS where PATHEXT is N/A
    exe_path = fake_pi_dir / "pi"
    recorder_py_posix = recorder_py.as_posix()
    exe_path.write_text(f"#!/usr/bin/env python3\nexec(open({recorder_py_posix!r}).read())\n")
    try:
        exe_path.chmod(0o755)
    except OSError:
        # chmod may fail on Windows; the .cmd path handles that case
        pass

    # Windows PATHEXT-compatible launcher — ``shutil.which("pi")`` finds this
    # via the .cmd extension and invokes it through COMSPEC (cmd.exe).
    pi_cmd = fake_pi_dir / "pi.cmd"
    pi_cmd.write_text(
        f'@echo off\npython "{recorder_py}" %*\n',
    )

    return exe_path, recording_dir


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Set up a minimal project root with .audiagentic directory."""
    audiagentic_dir = tmp_path / ".audiagentic"
    audiagentic_dir.mkdir(parents=True)
    return tmp_path


# ── Test fixtures that inject fake Pi into the worker PATH ────────────────


@pytest.fixture
def gateway_pi_environment(
    monkeypatch,
    fake_pi_setup: tuple[Path, Path],
) -> dict[str, str]:
    """Inject fake Pi into PATH.

    The worker's _replacement_environment preserves PATH from the caller
    (_PASSTHROUGH_ENV), so injecting here makes the fake Pi discoverable
    inside the worker subprocess.
    """
    exe_path, recording_dir = fake_pi_setup

    # Prepend the fake pi directory to PATH so subprocess can find 'pi'
    fake_dir = str(exe_path.parent)
    existing_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{existing_path}")

    return {
        "recording_dir": str(recording_dir),
        "argv_file": str(recording_dir / "test_argv.json"),
        "stdin_file": str(recording_dir / "test_stdin.txt"),
    }


@pytest.fixture
def pi_profile_setup(project_root: Path) -> None:
    """Create a default agent profile for the pi provider and enable it."""
    from audiagentic.components.agents.models.execution_profile_api import (
        create_execution_profile,
    )
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.state import set_implementation_state

    create_execution_profile(
        project_root,
        {
            "profile_id": "default",
            "provider_id": "pi",
            "instances": ["brutus/coder-quality-mid"],
            "is_default": True,
            "params": {"max-concurrency": 1},
        },
    )
    set_implementation_state(project_root, "providers", "pi", ImplementationState(enabled=True))


class TestGatewayPiSmokeStdinDelivery:
    """Full gateway dispatch proves Pi receives multiline prompt via stdin."""

    def test_multiline_reaches_pi_via_stdin_through_gateway(
        self,
        tmp_path: Path,
        project_root: Path,
        pi_profile_setup: None,
        gateway_pi_environment: dict[str, str],
    ) -> None:
        """Gateway-managed dispatch proves:

        1. Command is ``pi --print`` with no prompt argument.
        2. Full multiline prompt (including newlines) arrives via stdin.
        3. Result output contains no raw traceback or diagnostic leakage.

        This exercises the full gateway worker/provider dispatch path — the
        Pi adapter is invoked inside an isolated subprocess, and a controllable
        fake Pi records what it receives.
        """
        recording_dir = Path(gateway_pi_environment["recording_dir"])
        argv_file = recording_dir / "test_argv.json"
        stdin_file = recording_dir / "test_stdin.txt"

        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerExecutionIdentity,
        )
        from audiagentic.components.agents.gateway.queue.worker import (
            execute_isolated_provider_turn,
        )

        identity = WorkerExecutionIdentity(
            worker_id="smoke-worker",
            attempt_epoch=1,
            manifest_id="smoke-manifest",
            context_fingerprint="a" * 64,
            project_root=str(project_root.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        execution_request = {
            "project-root": str(project_root.resolve()),
            "provider-id": "pi",
            "model-id": "brutus/coder-quality-mid",
            "model-alias": None,
            "packet-data": {
                "prompt-body": MULTILINE_PROMPT,
                "metadata": {},
            },
            "worker-id": "smoke-worker",
            "attempt-epoch": 1,
            "provider-isolation-tier": "full-isolation",
        }

        # ── Execute through the isolated worker dispatch ───────────────
        result = execute_isolated_provider_turn(
            identity=identity,
            execution_request=execution_request,
            timeout_seconds=60,
        )

        # ── Step 1: Verify the dispatch succeeded ──────────────────────
        assert result.provider_id == "pi"
        assert result.result_data is not None

        # ── Step 2: Inspect what the fake Pi received (argv) ───────────
        assert argv_file.exists(), "Fake Pi was never invoked — argv file missing"
        captured_argv = json.loads(argv_file.read_text())

        # The command must be: [fake_exe, "--print", "--model", model-id]
        # NO prompt body arguments.
        assert "--print" in captured_argv, (
            f"--print not in command args (SH21 regression): {captured_argv}"
        )

        # CRITICAL: no part of the prompt body must appear as a CLI argument
        for arg in captured_argv[1:]:
            assert "Implement the following" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {captured_argv}"
            )
            assert "calculate" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {captured_argv}"
            )

        # ── Step 3: Inspect what the fake Pi received (stdin) ──────────
        assert stdin_file.exists(), "Fake Pi was never invoked — stdin file missing"
        captured_stdin = stdin_file.read_text()

        # The full multiline prompt must be present via stdin with newlines intact.
        # Note: the gateway may wrap the prompt with additional context, so we
        # check that the original prompt body is embedded in the stdin content.
        assert MULTILINE_PROMPT in captured_stdin, (
            f"Stdin content does not contain the original prompt. Got {len(captured_stdin)} chars.\n"
            f"Captured stdin starts: {repr(captured_stdin[:120])}"
        )

        # Verify the first line of the original prompt is preserved (SH21 regression)
        assert "Implement the following:\n" in captured_stdin, (
            f"First newline was lost (SH21 regression). Start of stdin: {repr(captured_stdin[:30])}"
        )

        # Verify all embedded newlines survived
        expected_newlines = MULTILINE_PROMPT.count("\n")
        actual_newlines = captured_stdin.count("\n")
        assert actual_newlines == expected_newlines, (
            f"Newline count mismatch. Expected {expected_newlines}, got {actual_newlines}"
        )

    def test_public_output_remains_redacted(
        self,
        tmp_path: Path,
        project_root: Path,
        pi_profile_setup: None,
        gateway_pi_environment: dict[str, str],
    ) -> None:
        """Verify that the public execution result does not contain raw
        traceback data or diagnostic leakage. The worker protocol pipe must
        carry only clean, bounded result envelopes.
        """
        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerExecutionIdentity,
        )
        from audiagentic.components.agents.gateway.queue.worker import (
            execute_isolated_provider_turn,
        )

        identity = WorkerExecutionIdentity(
            worker_id="redact-worker",
            attempt_epoch=1,
            manifest_id="redact-manifest",
            context_fingerprint="a" * 64,
            project_root=str(project_root.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        execution_request = {
            "project-root": str(project_root.resolve()),
            "provider-id": "pi",
            "model-id": "brutus/coder-quality-mid",
            "model-alias": None,
            "packet-data": {
                "prompt-body": MULTILINE_PROMPT,
                "metadata": {},
            },
            "worker-id": "redact-worker",
            "attempt-epoch": 1,
            "provider-isolation-tier": "full-isolation",
        }

        result = execute_isolated_provider_turn(
            identity=identity,
            execution_request=execution_request,
            timeout_seconds=60,
        )

        # The result_data should NOT contain traceback or raw diagnostic data
        result_mapping = result.to_mapping() if hasattr(result, "to_mapping") else result
        result_str = json.dumps(result_mapping, default=str)

        # No raw traceback in the public output
        assert "Traceback" not in result_str, "Raw traceback leaked into public execution result"
        assert "traceback" not in result_str.lower(), (
            "Traceback reference leaked into public execution result"
        )

        # No raw exception class names from the worker host internals
        assert "RuntimeError:" not in result_str, (
            "Raw exception leaked into public execution result"
        )

        # The result should be a clean bounded envelope
        assert result.provider_id == "pi"


class TestGatewayPiSmokeCommandShape:
    """Focused assertions on the command-line shape of the Pi dispatch."""

    def test_command_is_pi_print_no_prompt_arg(
        self,
        tmp_path: Path,
        project_root: Path,
        pi_profile_setup: None,
        gateway_pi_environment: dict[str, str],
    ) -> None:
        """The spawned command must be exactly ``pi --print [--model X]`` with
        NO prompt body argument. This is the SH21 fix boundary.

        Verifies that non-flag arguments in the command array contain only
        the model id, not any part of the prompt.
        """
        recording_dir = Path(gateway_pi_environment["recording_dir"])
        argv_file = recording_dir / "test_argv.json"

        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerExecutionIdentity,
        )
        from audiagentic.components.agents.gateway.queue.worker import (
            execute_isolated_provider_turn,
        )

        identity = WorkerExecutionIdentity(
            worker_id="shape-worker",
            attempt_epoch=1,
            manifest_id="shape-manifest",
            context_fingerprint="a" * 64,
            project_root=str(project_root.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        execution_request = {
            "project-root": str(project_root.resolve()),
            "provider-id": "pi",
            "model-id": "brutus/coder-quality-mid",
            "model-alias": None,
            "packet-data": {
                "prompt-body": MULTILINE_PROMPT,
                "metadata": {},
            },
            "worker-id": "shape-worker",
            "attempt-epoch": 1,
            "provider-isolation-tier": "full-isolation",
        }

        result = execute_isolated_provider_turn(
            identity=identity,
            execution_request=execution_request,
            timeout_seconds=60,
        )
        assert result.provider_id == "pi"

        # Inspect captured argv
        assert argv_file.exists()
        captured_argv = json.loads(argv_file.read_text())

        # Command shape: [executable, "--print", "--model", model-id]
        # The prompt must NOT be an argument
        assert "--print" in captured_argv
        assert "--model" in captured_argv
        assert "brutus/coder-quality-mid" in captured_argv

        # Count arguments that are NOT flags or the executable
        non_flag_args = [arg for arg in captured_argv[1:] if not arg.startswith("--")]
        # Only model-id should be a non-flag argument (not the prompt)
        assert non_flag_args == ["brutus/coder-quality-mid"], (
            f"Unexpected non-flag arguments (prompt leaked?): {captured_argv}"
        )


class TestGatewayPiSmokeErrorPathRedaction:
    """Verify redaction on error path through gateway dispatch."""

    def test_error_output_does_not_leak_worker_diagnostics(
        self,
        tmp_path: Path,
        project_root: Path,
        pi_profile_setup: None,
        monkeypatch,
    ) -> None:
        """When Pi's recipe runner raises an AudiaGenticError (simulated by
        having no pi executable), the error envelope must NOT contain raw
        traceback data. The worker host's _emit_worker_diagnostic writes to
        stderr only; the protocol pipe carries a clean error envelope.

        MA35: Pi now goes through the recipe path, so we patch require_executable
        at the base_runner/cli level instead of a hand-written adapter.

        We verify via the execute_provider API directly (no subprocess needed)
        since the redaction contract is at the adapter boundary, not the
        worker boundary. Worker-level diagnostics are already covered by
        test_sh21_prompt_truncation_and_diagnostics.py.
        """
        from audiagentic.components.providers.services.execution.execution import (
            execute_provider,
        )
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        def failing_require_executable(*args, **kwargs) -> str:
            # Mirror what the real cli.require_executable raises (cli.py:21):
            # a wrong code here made the assertion below untestable.
            raise AudiaGenticError(
                code="EXT-PROVCLI-001",
                kind="providers",
                message="executable not found: pi",
                details={"provider-id": "pi"},
            )

        # base_runner does `from ...adapters.cli import require_executable` at
        # import time, so patching the name on `cli` is a no-op and this test
        # used to execute a REAL provider against a REAL model. Patch the bound
        # name in base_runner, which is what line 173 actually calls.
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.require_executable",
            failing_require_executable,
        )

        with pytest.raises(AudiaGenticError) as exc_info:
            execute_provider(
                provider_id="pi",
                packet_ctx={
                    "provider-id": "pi",
                    "model-id": "brutus/coder-quality-mid",
                    "prompt-body": MULTILINE_PROMPT,
                },
                provider_cfg={"enabled": True, "access-mode": "cli"},
            )

        # The error code should be the provider CLI error code
        assert exc_info.value.code == "EXT-PROVCLI-001"

        # The error message must NOT contain raw traceback
        error_str = str(exc_info.value)
        assert "Traceback" not in error_str, "Raw traceback leaked into public error envelope"
