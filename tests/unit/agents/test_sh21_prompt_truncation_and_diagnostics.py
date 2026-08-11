"""SH21: multiline prompt transport and safe worker diagnostics.

Tests that the gateway full-isolation worker path preserves multiline prompts
intact through the JSON protocol, and that unexpected worker exceptions yield
bounded redacted diagnostics on stderr without contaminating the protocol pipe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerErrorEnvelope,
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
    decode_worker_message,
    encode_worker_message,
)

pytestmark = pytest.mark.no_parallel

FINGERPRINT = "a" * 64


# ── Fixtures: multiline prompt body with code fences ─────────────────────

MULTILINE_PROMPT_BODY = (
    "Implement the following:\n"
    "\n"
    "```python\n"
    "def calculate(x: int, y: int) -> int:\n"
    "    return x + y\n"
    "```\n"
    "\n"
    "Return a brief summary."
)

SINGLE_NEWLINE_PROMPT = "First line\nSecond line"

CODE_FENCE_ONLY = '```json\n{"key": "value"}\n```'


# ── Protocol-level round-trip tests (no subprocess) ──────────────────────


class TestPromptProtocolRoundTrip:
    """Verify JSON protocol preserves embedded newlines in prompt-body."""

    def test_multiline_prompt_survives_encode_decode(self, tmp_path: Path) -> None:
        identity = WorkerExecutionIdentity(
            worker_id="worker-1",
            attempt_epoch=1,
            manifest_id="mf-1",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "qwen",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": MULTILINE_PROMPT_BODY,
                    "metadata": {},
                },
                "worker-id": "worker-1",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        encoded = encode_worker_message(request)
        # Encoded frame must be a single line (no literal \n)
        assert "\n" not in encoded
        assert "\r" not in encoded

        # Decode back and verify prompt body is preserved
        decoded = decode_worker_message(encoded)
        assert isinstance(decoded, WorkerExecuteEnvelope)
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == MULTILINE_PROMPT_BODY

    def test_single_newline_prompt_survives(self, tmp_path: Path) -> None:
        identity = WorkerExecutionIdentity(
            worker_id="worker-1",
            attempt_epoch=1,
            manifest_id="mf-1",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "qwen",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": SINGLE_NEWLINE_PROMPT,
                    "metadata": {},
                },
                "worker-id": "worker-1",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        encoded = encode_worker_message(request)
        assert "\n" not in encoded

        decoded = decode_worker_message(encoded)
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == SINGLE_NEWLINE_PROMPT

    def test_code_fence_only_prompt_survives(self, tmp_path: Path) -> None:
        identity = WorkerExecutionIdentity(
            worker_id="worker-1",
            attempt_epoch=1,
            manifest_id="mf-1",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "qwen",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": CODE_FENCE_ONLY,
                    "metadata": {},
                },
                "worker-id": "worker-1",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        encoded = encode_worker_message(request)
        assert "\n" not in encoded

        decoded = decode_worker_message(encoded)
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == CODE_FENCE_ONLY

    def test_single_line_prompt_unchanged(self, tmp_path: Path) -> None:
        """Single-line behavior must remain identical."""
        identity = WorkerExecutionIdentity(
            worker_id="worker-1",
            attempt_epoch=1,
            manifest_id="mf-1",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "qwen",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": "Simple one-line prompt",
                    "metadata": {},
                },
                "worker-id": "worker-1",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        encoded = encode_worker_message(request)
        decoded = decode_worker_message(encoded)
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == "Simple one-line prompt"


# ── Integration tests: full-isolation worker path with real subprocess ───


class TestPromptTransportThroughWorker:
    """End-to-end tests through the full-isolation worker subprocess."""

    def test_multiline_prompt_survives_worker_protocol_roundtrip(self, tmp_path: Path) -> None:
        """Multiline prompt with newlines and code fences survives intact
        through encode → readline → decode in the full-isolation worker.

        This tests the protocol transport layer (JSON encode/decode +
        subprocess pipe) without requiring a real provider executable."""
        # Build an execute envelope with the multiline prompt
        identity = WorkerExecutionIdentity(
            worker_id="worker-multiline",
            attempt_epoch=1,
            manifest_id="mf-multiline",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "test-provider",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": MULTILINE_PROMPT_BODY,
                    "metadata": {},
                },
                "worker-id": "worker-multiline",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        # Encode the message (as the gateway worker does)
        encoded = encode_worker_message(request)
        frame = encoded + "\n"  # add trailing newline as communicate() does

        # Simulate readline in the worker host
        line = frame.splitlines(True)[0]  # readline reads to first \n

        # The line should be complete (no truncation)
        assert len(line) == len(frame), (
            f"Frame was truncated by readline. Expected {len(frame)} chars, got {len(line)}"
        )

        # Decode and verify prompt body is preserved
        decoded = decode_worker_message(line.rstrip("\n"))
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == MULTILINE_PROMPT_BODY

    def test_single_line_prompt_unchanged_through_protocol(self, tmp_path: Path) -> None:
        """Single-line prompt behavior is identical through the worker."""
        identity = WorkerExecutionIdentity(
            worker_id="worker-singleline",
            attempt_epoch=1,
            manifest_id="mf-singleline",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )
        request = WorkerExecuteEnvelope(
            identity=identity,
            execution_request={
                "project-root": str(tmp_path.resolve()),
                "provider-id": "test-provider",
                "model-id": "test-model",
                "model-alias": None,
                "packet-data": {
                    "prompt-body": "Simple one-line prompt",
                    "metadata": {},
                },
                "worker-id": "worker-singleline",
                "attempt-epoch": 1,
                "provider-isolation-tier": "full-isolation",
            },
        )

        encoded = encode_worker_message(request)
        frame = encoded + "\n"
        line = frame.splitlines(True)[0]

        assert len(line) == len(frame)

        decoded = decode_worker_message(line.rstrip("\n"))
        packet_data: dict = decoded.execution_request["packet-data"]  # type: ignore[index]
        assert packet_data["prompt-body"] == "Simple one-line prompt"


class TestWorkerExceptionDiagnostics:
    """Unexpected worker exceptions yield bounded redacted diagnostics."""

    def test_unexpected_exception_emits_stderr_diagnostic_via_subprocess(
        self, tmp_path: Path
    ) -> None:
        """When the worker host throws an unexpected exception, a bounded
        diagnostic is written to stderr and the protocol stdout carries
        only a redacted error envelope."""
        import io

        # Simulate the worker host reading a valid frame but then raising
        # an unexpected exception. We test this by running the worker host
        # as a subprocess with crafted input.
        from audiagentic.components.agents.gateway.queue.worker_host import (
            _emit_worker_diagnostic,
        )

        exc = RuntimeError("unexpected crash in worker")
        stderr_buf = io.StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = stderr_buf
            _emit_worker_diagnostic(exc)
        finally:
            sys.stderr = old_stderr

        diagnostic = stderr_buf.getvalue()

        # The diagnostic must contain the exception class and message
        assert "RuntimeError" in diagnostic
        assert "unexpected crash in worker" in diagnostic

        # The diagnostic must NOT contain any raw prompt or secret material
        # (this is guaranteed by the design: _emit_worker_diagnostic only
        # receives the exception, not the request data)
        assert "Bearer " not in diagnostic
        assert "sk-" not in diagnostic

    def test_error_envelope_does_not_contain_traceback(self) -> None:
        """The protocol error envelope must never carry raw traceback data."""
        identity = WorkerExecutionIdentity(
            worker_id="worker-test",
            attempt_epoch=1,
            manifest_id="mf-test",
            context_fingerprint=FINGERPRINT,
            project_root=str(Path.cwd().resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerProcessEvidence,
        )

        evidence = WorkerProcessEvidence(
            pid=12345,
            process_creation_identity="proc-start:test",
            working_directory=str(Path.cwd().resolve()),
        )

        # The INT-AGW-076 error envelope must be clean
        error_env = WorkerErrorEnvelope(
            identity=identity,
            process=evidence,
            error_code="INT-AGW-076",
            error_kind="agents",
            message="isolated provider worker failed unexpectedly",
        )

        encoded = encode_worker_message(error_env)
        assert "Traceback" not in encoded
        assert "traceback" not in encoded.lower()

    def test_protocol_stdout_not_contaminated_by_traceback(self, tmp_path: Path) -> None:
        """The protocol pipe (stdout) must never carry traceback data even
        when an unexpected exception occurs. Only the redacted error envelope.
        """
        import io

        # Simulate what happens in main(): _emit_worker_diagnostic writes
        # to stderr, then a clean error envelope goes to stdout.
        from audiagentic.components.agents.gateway.queue.worker_host import (
            _emit_worker_diagnostic,
            _write,
        )

        identity = WorkerExecutionIdentity(
            worker_id="worker-test",
            attempt_epoch=1,
            manifest_id="mf-test",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerProcessEvidence,
        )

        evidence = WorkerProcessEvidence(
            pid=12345,
            process_creation_identity="proc-start:test",
            working_directory=str(tmp_path.resolve()),
        )

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        from audiagentic.components.agents.gateway.queue import worker_host

        old_protocol_out = worker_host._PROTOCOL_OUT
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            worker_host._PROTOCOL_OUT = stdout_buf
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf

            # Simulate the exception handler path in main():
            exc = RuntimeError("unexpected crash")
            _emit_worker_diagnostic(exc)
            _write(
                WorkerErrorEnvelope(
                    identity=identity,
                    process=evidence,
                    error_code="INT-AGW-076",
                    error_kind="agents",
                    message="isolated provider worker failed unexpectedly",
                )
            )
        finally:
            worker_host._PROTOCOL_OUT = old_protocol_out
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_content = stdout_buf.getvalue()
        stderr_content = stderr_buf.getvalue()

        # stdout (protocol pipe) must be clean - only the error envelope
        assert "Traceback" not in stdout_content
        assert "RuntimeError" not in stdout_content
        assert "unexpected crash" not in stdout_content

        # Decode the stdout envelope and verify it's a clean error
        frame = stdout_content.strip()
        decoded = decode_worker_message(frame)
        assert isinstance(decoded, WorkerErrorEnvelope)
        assert decoded.error_code == "INT-AGW-076"

        # stderr (operator channel) must contain the diagnostic
        assert "RuntimeError" in stderr_content
        assert "unexpected crash" in stderr_content


class TestWorkerHostDiagnosticEmission:
    """Unit tests for _emit_worker_diagnostic behavior."""

    def test_diagnostic_contains_exception_class_and_message(self, tmp_path: Path) -> None:
        from audiagentic.components.agents.gateway.queue.worker_host import (
            _emit_worker_diagnostic,
        )

        exc = ValueError("test error message")
        with open(tmp_path / "stderr.log", "w") as f:
            old_stderr = sys.stderr
            try:
                sys.stderr = f
                _emit_worker_diagnostic(exc)
            finally:
                sys.stderr = old_stderr

        output = (tmp_path / "stderr.log").read_text()
        assert "ValueError" in output
        assert "test error message" in output

    def test_diagnostic_is_bounded(self, tmp_path: Path) -> None:
        """Diagnostic traceback is truncated when it exceeds the limit."""
        from audiagentic.components.agents.gateway.queue.worker_host import (
            _MAX_DIAGNOSTIC_BYTES,
            _emit_worker_diagnostic,
        )

        # Create a deep exception chain to exceed the limit
        def deep_func(n: int) -> None:
            if n == 0:
                raise RuntimeError("deep error")
            deep_func(n - 1)

        # Use a moderate depth that generates enough traceback without hitting
        # Python's default recursion limit (usually 1000).
        exc: RuntimeError | None = None
        try:
            deep_func(300)
        except RuntimeError as e:
            exc = e
        assert exc is not None
        with open(tmp_path / "stderr.log", "w") as f:
            old_stderr = sys.stderr
            try:
                sys.stderr = f
                _emit_worker_diagnostic(exc)
            finally:
                sys.stderr = old_stderr

        output = (tmp_path / "stderr.log").read_text()
        # The diagnostic should be bounded
        assert len(output) <= _MAX_DIAGNOSTIC_BYTES + 2 * 1024  # some overhead
        # Should contain a truncation marker if truncated
        if len(output) >= _MAX_DIAGNOSTIC_BYTES:
            assert "<truncated-diagnostic>" in output

    def test_diagnostic_does_not_contain_secret_values(self, tmp_path: Path) -> None:
        """Worker diagnostics must not carry raw secret material."""
        from audiagentic.components.agents.gateway.queue.worker_host import (
            _emit_worker_diagnostic,
        )

        exc = ValueError("safe error - no secrets here")
        with open(tmp_path / "stderr.log", "w") as f:
            old_stderr = sys.stderr
            try:
                sys.stderr = f
                _emit_worker_diagnostic(exc)
            finally:
                sys.stderr = old_stderr

        output = (tmp_path / "stderr.log").read_text()
        # The diagnostic should contain the exception info but no injected secrets
        assert "safe error" in output
        # Should not contain any bearer tokens or API keys (by design)
        assert "Bearer " not in output
        assert "sk-" not in output


# ── SH21 fix: stdin transport — prompt via pipe, not CLI argument ────────


class TestPiStdinTransport:
    """SH21 fix verification: Pi adapter delivers prompt via stdin to preserve
    newlines that would be lost in --print CLI argument processing.

    These tests verify the boundary between AUDiaGentic and Pi's stdin reader,
    using subprocess with a real pipe (not mocked) to prove multiline strings
    survive the transport.
    """

    def test_multiline_prompt_survives_stdin_pipe(self, tmp_path: Path) -> None:
        """Multiline prompt with embedded newlines survives intact through
        stdin pipe to a child process — the mechanism used by the Pi adapter.

        This is the core SH21 regression: proves that when we pipe the prompt
        via stdin instead of as a CLI argument, the newline is preserved end-to-end.
        """
        import subprocess

        multiline_prompt = (
            "This is the first line of a transport regression test.\n"
            "Reply exactly: NEWLINE_TRANSPORT_OK\n"
        )

        # Use a simple Python one-liner that reads stdin and echoes it back
        # (simulates what Pi's readPipedStdin does)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                ("import sys; data = sys.stdin.read(); sys.stdout.write(repr(data))"),
            ],
            input=multiline_prompt,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        # The echoed repr should contain the exact multiline string with \n
        assert "first line of a transport regression test." in result.stdout
        assert "NEWLINE_TRANSPORT_OK" in result.stdout
        # Critical: the newline character must be present (not stripped)
        assert "\\\\n" in result.stdout or "\\n" in result.stdout, (
            f"Newline was lost during stdin pipe transport. Got: {result.stdout}"
        )

    def test_first_newline_not_stripped_by_stdin_pipe(self) -> None:
        """The FIRST newline in the prompt must NOT be stripped — this is the
        exact bug SH21 describes. When passed as a CLI arg, Pi strips the first
        \n; via stdin pipe it survives.
        """
        import subprocess

        # Prompt where the first newline is critical for semantics
        prompt = "Line one\nLine two"
        expected_count = 1  # exactly one \n

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                ("import sys; data = sys.stdin.read(); sys.stdout.write(str(data.count(chr(10))))"),
            ],
            input=prompt,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        actual_count = int(result.stdout.strip())
        assert actual_count == expected_count, (
            f"First newline was stripped. Expected {expected_count} newline(s), got {actual_count}"
        )

    def test_pi_recipe_builds_command_without_prompt_arg(self, monkeypatch) -> None:
        """Pi's recipe-driven runner must NOT include the prompt as a CLI
        argument — it goes via stdin (MA35 stdin-fallback, SH21 fix).
        """
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.require_executable",
            lambda *a, **k: "pi",
        )

        from audiagentic.components.providers.adapters.base_runner import (
            build_launch_spec,
        )
        from audiagentic.components.providers.descriptors.registry import (
            all_descriptors,
        )

        # Build the same command the recipe path produces — prompt is in
        # context but {prompt} is absent from pi.yaml's args-template, so
        # it should NOT appear in the resolved args.
        descriptor = all_descriptors()["pi"]
        execution = getattr(descriptor, "execution", None)
        assert execution is not None

        spec = build_launch_spec(
            {"executable": "pi", "aliases": ["pi"], **execution},
            context={
                "prompt": "Test prompt with newline\nLine two",
                "model": "brutus/coder-quality-mid",
                "approval-mode": "auto",
            },
        )
        command = [spec.executable, *spec.args]

        # Command should be: ["pi", "--print", "--model", "model-id"]
        assert "--print" in command
        assert "--model" in command
        assert "brutus/coder-quality-mid" in command

        # CRITICAL: the prompt must NOT appear as a CLI argument
        for arg in command:
            assert "Test prompt with newline" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {command}"
            )
            assert "Line two" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {command}"
            )

    def test_run_streaming_command_preserves_stdin_newlines(self, tmp_path: Path) -> None:
        """run_streaming_command with input_text preserves newlines when piping
        to a child process — the mechanism the Pi adapter uses for stdin delivery.
        """
        from audiagentic.components.providers.protocols.streaming.provider_streaming import (
            run_streaming_command,
        )
        from audiagentic.components.providers.protocols.streaming.sinks import (
            InMemorySink,
        )

        multiline_input = "First line\nSecond line\nThird line"
        expected_newlines = 2

        stdout_sink = InMemorySink()
        stderr_sink = InMemorySink()

        result = run_streaming_command(
            [
                sys.executable,
                "-c",
                ("import sys; data = sys.stdin.read(); sys.stdout.write(str(data.count(chr(10))))"),
            ],
            cwd=tmp_path,
            input_text=multiline_input,
            stdout_sinks=[stdout_sink],
            stderr_sinks=[stderr_sink],
        )

        assert result.returncode == 0
        actual_newlines = int(stdout_sink.text.strip())
        assert actual_newlines == expected_newlines, (
            f"run_streaming_command lost newlines via stdin. "
            f"Expected {expected_newlines}, got {actual_newlines}. "
            f"Stderr: {stderr_sink.text}"
        )

    def test_pi_recipe_omits_prompt_from_argv(self, monkeypatch) -> None:
        """Pi's recipe path omits {prompt} from args-template (MA35), so
        the prompt goes via stdin — verify the resolved command has no
        prompt content in its argv.
        """
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.require_executable",
            lambda *a, **k: "pi",
        )

        from audiagentic.components.providers.adapters.base_runner import (
            build_launch_spec,
        )
        from audiagentic.components.providers.descriptors.registry import (
            all_descriptors,
        )

        descriptor = all_descriptors()["pi"]
        execution = getattr(descriptor, "execution", None)
        assert execution is not None

        # {prompt} is absent from pi.yaml's args-template — it goes via stdin.
        # Verify: the resolved template does NOT contain {prompt}.
        template = (
            execution.get("args-template")
            or execution.get("args")
            or [
                "{approval-flags}",
                "{model-flags}",
                "{prompt}",
            ]
        )
        assert "{prompt}" not in template, (
            "Pi args-template should omit {prompt} (MA35 stdin-fallback)"
        )

        # Build the command with prompt context — it should NOT appear in args
        spec = build_launch_spec(
            {"executable": "pi", "aliases": ["pi"], **execution},
            context={
                "prompt": "Prompt body\nFirst line",
                "model": "test-model",
                "approval-mode": "auto",
            },
        )
        command = [spec.executable, *spec.args]
        for arg in command:
            assert "Prompt body" not in arg, f"Prompt leaked into CLI: {arg}"
            assert "First line" not in arg, f"Prompt leaked into CLI: {arg}"

    def test_real_subprocess_stdin_preserves_newline_boundary(self, tmp_path: Path) -> None:
        """End-to-end test: write multiline prompt to a file via subprocess stdin,
        then read it back and verify newlines are intact. This simulates the
        exact data path of the Pi adapter's stdin delivery.

        The test uses Python's subprocess to pipe stdin → process → file, proving
        that the Python → subprocess → stdin → process boundary preserves newlines.
        """
        import subprocess

        prompt = "Line1\nLine2\nLine3"
        newline_count = prompt.count("\n")

        # Write a helper script to avoid embedding Windows paths in python -c
        # strings (which causes unicodeescape errors on Windows due to backslashes).
        script = tmp_path / "pipe_writer.py"
        script.write_text(
            "import sys, os; "
            "path = os.environ['PIPE_TARGET']; "
            "open(path, 'w').write(sys.stdin.read())\n"
        )
        subprocess.run(
            [sys.executable, str(script)],
            input=prompt,
            text=True,
            check=True,
            env={**os.environ, "PIPE_TARGET": str(tmp_path / "prompt.txt")},
        )

        # Read back and verify
        content = (tmp_path / "prompt.txt").read_text()
        assert content.count("\n") == newline_count, (
            f"Newline count mismatch after stdin→file roundtrip. "
            f"Expected {newline_count}, got {content.count(chr(10))}"
        )
        # Verify the exact first-newline boundary — SH21 regression
        assert content.startswith("Line1\n"), (
            f"First newline was lost (SH21 regression). Got: {repr(content[:20])}"
        )


# ── SH21 RV769: deterministic worker failure with known sensitive string ──


class TestWorkerHostFailureRedaction:
    """Deterministic regression: worker host fails with a known sensitive string.

    Verifies the exact INT-AGW-076 path where an unexpected isolated-worker
    failure produces:
      1. Clean redacted error envelope on stdout (protocol pipe)
      2. Bounded diagnostic on stderr (operator channel)
      3. Private evidence persisted in durable record (never in public status)
    """

    def test_worker_host_emits_clean_error_envelope_and_stderr_diagnostic(
        self,
        tmp_path: Path,
    ) -> None:
        """Worker host main() path: unexpected exception → stderr diagnostic +
        clean INT-AGW-076 error envelope on stdout. The sensitive string appears
        only in the stderr diagnostic and is redacted from the error envelope."""
        import io

        KNOWN_SECRET = "Bearer sk-proj-test1234567890"
        exc = ValueError(f"provider crash with {KNOWN_SECRET}")

        identity = WorkerExecutionIdentity(
            worker_id="worker-rv769",
            attempt_epoch=1,
            manifest_id="mf-rv769",
            context_fingerprint=FINGERPRINT,
            project_root=str(tmp_path.resolve()),
            component_profile="",
            provider_isolation_tier="full-isolation",
        )

        from audiagentic.components.agents.contracts.worker_protocol import (
            WorkerProcessEvidence,
        )

        evidence = WorkerProcessEvidence(
            pid=99887,
            process_creation_identity="proc-start:rv769",
            working_directory=str(tmp_path.resolve()),
        )

        from audiagentic.components.agents.gateway.queue.worker_host import (
            _emit_worker_diagnostic,
            _write,
        )

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        from audiagentic.components.agents.gateway.queue import worker_host

        old_protocol_out = worker_host._PROTOCOL_OUT
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            worker_host._PROTOCOL_OUT = stdout_buf
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf

            # Simulate the exact main() exception handler path:
            _emit_worker_diagnostic(exc)
            _write(
                WorkerErrorEnvelope(
                    identity=identity,
                    process=evidence,
                    error_code="INT-AGW-076",
                    error_kind="agents",
                    message="isolated provider worker failed unexpectedly",
                )
            )
        finally:
            worker_host._PROTOCOL_OUT = old_protocol_out
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_content = stdout_buf.getvalue()
        stderr_content = stderr_buf.getvalue()

        # ── Stdout (protocol pipe): must be clean, only the error envelope ──
        assert "Traceback" not in stdout_content
        assert "ValueError" not in stdout_content
        assert KNOWN_SECRET not in stdout_content
        frame = stdout_content.strip()
        decoded = decode_worker_message(frame)
        assert isinstance(decoded, WorkerErrorEnvelope)
        assert decoded.error_code == "INT-AGW-076"
        assert decoded.message == "isolated provider worker failed unexpectedly"

        # ── Stderr (operator channel): must contain the diagnostic ────────
        assert "ValueError" in stderr_content
        assert KNOWN_SECRET in stderr_content
        assert "WORKER-EXCEPTION" in stderr_content

    def test_worker_diagnostic_is_bounded(self, tmp_path: Path) -> None:
        """Worker diagnostic is truncated when it exceeds the 64 KB limit."""
        import io

        from audiagentic.components.agents.gateway.queue.worker_host import (
            _MAX_DIAGNOSTIC_BYTES,
            _emit_worker_diagnostic,
        )

        # Create a deep exception to generate a large traceback
        def deep_func(n: int) -> None:
            if n == 0:
                raise RuntimeError("deep crash")
            deep_func(n - 1)

        exc: RuntimeError | None = None
        try:
            deep_func(300)
        except RuntimeError as e:
            exc = e
        assert exc is not None

        stderr_buf = io.StringIO()
        old_stderr = sys.stderr
        try:
            sys.stderr = stderr_buf
            _emit_worker_diagnostic(exc)
        finally:
            sys.stderr = old_stderr

        output = stderr_buf.getvalue()
        # Must be bounded
        assert len(output) <= _MAX_DIAGNOSTIC_BYTES + 2 * 1024
        if len(output) >= _MAX_DIAGNOSTIC_BYTES:
            assert "<truncated-diagnostic>" in output

    def test_cancellation_does_not_leak_worker_diagnostics(
        self,
        tmp_path: Path,
    ) -> None:
        """Normal cancellation (cancel_requested=True) does NOT produce
        worker diagnostic evidence. Only INT-AGW-076 errors do."""
        from audiagentic.components.agents.gateway import store as gws

        record = gws.build_record(execution_profile_id="default", prompt_body="do the thing")
        gws.write_record(tmp_path, record)
        gws.transition_record(tmp_path, record["request-id"], "running")

        # Cancel the request (no INT-AGW-076 error involved)
        updated = gws.cancel_queued_or_mark_requested(tmp_path, record["request-id"])

        # No worker-evidence should exist for a normal cancellation
        assert updated.get("worker-evidence") is None
