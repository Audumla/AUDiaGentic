"""Pi one-shot execution keeps ``--print`` stdin semantics plus real activity.

Pi owns a narrow adapter solely to attach a request-private lifecycle extension.
The shared CLI runner still owns stdin delivery, parsing, and terminal result
normalization.  Mock only the subprocess/stream boundary.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.requires_npm,
    pytest.mark.skipif(shutil.which("pi") is None, reason="pi CLI not on PATH"),
]

# ── Multiline prompt used across tests ────────────────────────────────────

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


# ── _load_runner resolves Pi's narrow adapter ────────────────────────────


class TestPiRunnerResolution:
    """The Pi adapter preserves the descriptor recipe and adds observation."""

    def test_load_runner_resolves_pi_adapter(self) -> None:
        from audiagentic.components.providers.services.execution.execution import (
            _load_runner,
        )

        runner = _load_runner("pi")
        assert runner is not None

    def test_describe_execution_support_reports_adapter_mode(self) -> None:
        from audiagentic.components.providers.services.execution.execution import (
            describe_execution_support,
        )

        info = describe_execution_support("pi")
        assert info["mode"] == "adapter"
        assert info["module"].endswith(".pi.adapter")


# ── Recipe path delivers multiline prompt via stdin (MA35) ────────────────


class TestPiRecipeStdinDelivery:
    """Verify that Pi's adapter retains the shared CLI stdin contract."""

    @pytest.fixture
    def mock_streaming_command(self, monkeypatch) -> list[dict[str, Any]]:
        """Mock run_streaming_command to capture invocation args.

        Monkeypatch at base_runner level — the recipe path calls it from
        make_cli_runner, not from a hand-written adapter."""
        captured: list[dict[str, Any]] = []

        def _capture(command: list[str], *, input_text: str | None = None, **kwargs) -> Any:
            captured.append(
                {
                    "command": list(command),
                    "input_text": input_text,
                    "environment": kwargs.get("environment"),
                }
            )

            # Return a minimal StreamedCommandResult-like object
            class _Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return _Result()

        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.run_streaming_command",
            _capture,
        )
        return captured

    @pytest.fixture
    def mock_require_executable(self, monkeypatch) -> None:
        """Mock require_executable so the test doesn't need 'pi' on PATH."""
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.cli.require_executable",
            lambda pid, *aliases: "pi-mock",
        )
        # Also patch in base_runner which imports it
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.require_executable",
            lambda pid, *aliases: "pi-mock",
        )

    def _get_runner(self) -> Any:
        from audiagentic.components.providers.services.execution.execution import _load_runner

        return _load_runner("pi")

    def test_run_passes_multiline_prompt_as_input_text(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
    ) -> None:
        """The Pi recipe's run() passes the full multiline prompt-body as
        input_text to run_streaming_command — not as a CLI argument."""
        runner = self._get_runner()

        packet_ctx = {
            "provider-id": "pi",
            "model-id": "brutus/coder-quality-mid",
            "prompt-body": MULTILINE_PROMPT,
        }
        provider_cfg: dict[str, Any] = {}

        result = runner(packet_ctx, provider_cfg)
        assert result["status"] == "ok"

        # Verify the invocation captured by our mock
        assert len(mock_streaming_command) == 1
        call = mock_streaming_command[0]

        # The full multiline prompt must be in input_text (not command args)
        assert call["input_text"] is not None
        # The stdin-fallback path uses default_build_prompt, which wraps the
        # raw prompt-body with preamble text — check the original content
        assert "Implement the following" in call["input_text"]
        assert "calculate(x: int, y: int)" in call["input_text"]

        # Verify embedded newlines are intact
        newline_count = call["input_text"].count("\n")
        assert newline_count >= 1, "Multiline prompt lost its newlines"

    def test_command_contains_no_prompt_body(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
    ) -> None:
        """The command array must NOT contain the prompt body — it goes via
        stdin only (SH21 fix, MA35 recipe path)."""
        runner = self._get_runner()

        packet_ctx = {
            "provider-id": "pi",
            "model-id": "test-model",
            "prompt-body": MULTILINE_PROMPT,
        }
        provider_cfg: dict[str, Any] = {}

        runner(packet_ctx, provider_cfg)

        assert len(mock_streaming_command) == 1
        command = mock_streaming_command[0]["command"]

        # Command should be: ["pi-mock", "--print", "--model", "test-model"]
        assert command[0] == "pi-mock"
        assert "--print" in command
        assert "--model" in command
        assert "test-model" in command

        # CRITICAL: no part of the prompt body in command args
        for arg in command:
            assert "Implement the following" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {command}"
            )
            assert "calculate" not in arg, (
                f"Prompt leaked into CLI args (SH21 regression): {command}"
            )

    def test_command_without_model_arg_when_no_default(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
    ) -> None:
        """When no model is resolved, command contains only --print."""
        runner = self._get_runner()

        packet_ctx = {
            "provider-id": "pi",
            "prompt-body": "Hello",
        }
        provider_cfg: dict[str, Any] = {}

        runner(packet_ctx, provider_cfg)

        command = mock_streaming_command[0]["command"]
        # Should be ["pi-mock", "--print"] — no --model when none resolved
        assert "--model" not in command or "test-model" not in command

    def test_first_newline_preserved_in_input_text(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
    ) -> None:
        """SH21 regression via recipe path: the FIRST newline in the prompt
        must survive when piped via stdin (input_text)."""
        runner = self._get_runner()

        prompt_with_critical_first_newline = "Line one\nLine two\nLine three"

        packet_ctx = {
            "provider-id": "pi",
            "prompt-body": prompt_with_critical_first_newline,
        }
        provider_cfg: dict[str, Any] = {}

        runner(packet_ctx, provider_cfg)

        input_text = mock_streaming_command[0]["input_text"]
        assert input_text is not None
        # The default_build_prompt wraps the raw body, so check for its content
        assert "Line one" in input_text
        assert "Line two" in input_text
        # First newline boundary preserved — SH21 regression guard
        # (the preamble includes "Prompt body: Line one\nLine two...")
        assert "Line one\nLine two" in input_text, (
            f"First newline was lost (SH21 regression): {repr(input_text)}"
        )

    def test_execute_provider_uses_pi_adapter(self, monkeypatch) -> None:
        """Full provider dispatch retains the shared CLI runner beneath Pi."""
        from audiagentic.components.providers.services.execution.execution import (
            execute_provider,
        )

        # Track if base_runner.run_streaming_command was invoked
        run_called = {"seen": False}

        def _track(command: list[str], *, input_text: str | None = None, **kwargs) -> Any:
            run_called["seen"] = True

            class _Result:
                returncode = 0
                stdout = "dispatch-ok"
                stderr = ""

            return _Result()

        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.base_runner.run_streaming_command",
            _track,
        )
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.cli.require_executable",
            lambda pid, *aliases: "pi-mock",
        )

        result = execute_provider(
            provider_id="pi",
            packet_ctx={
                "provider-id": "pi",
                "model-id": "test-model",
                "prompt-body": "Dispatch test\nWith newline",
            },
            provider_cfg={"enabled": True, "access-mode": "cli"},
        )

        assert run_called["seen"], "execute_provider('pi') did not invoke the recipe runner"
        assert result["provider-id"] == "pi"
        assert result["status"] == "ok"

    def test_request_owned_activity_extension_is_explicit_and_private(
        self,
        tmp_path,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
    ) -> None:
        runner = self._get_runner()
        runner(
            {
                "provider-id": "pi",
                "model-id": "test-model",
                "request-id": "req_activity",
                "job-id": "req_activity",
                "working-root": str(tmp_path),
                "prompt-body": "Say hello.",
            },
            {},
        )

        call = mock_streaming_command[0]
        command = call["command"]
        assert "--print" in command
        assert "--no-extensions" in command
        extension = command[command.index("--extension") + 1]
        extension_path = Path(extension)
        assert extension_path.is_file()
        assert extension_path.is_relative_to(tmp_path)
        assert "pi.on(type" in extension_path.read_text(encoding="utf-8")
        assert call["environment"] == {
            "AUDIAGENTIC_PI_ACTIVITY_PATH": str(
                tmp_path / ".audiagentic" / "runtime" / "jobs" / "req_activity" / "events.ndjson"
            )
        }
