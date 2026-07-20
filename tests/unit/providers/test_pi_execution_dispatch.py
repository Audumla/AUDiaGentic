"""SH21: Pi adapter selection and stdin-piped execution.

Tests that the provider dispatch seam resolves the custom Pi adapter (not
the YAML descriptor runner) and that adapter.run delivers the full multiline
prompt via stdin (input_text) while the command contains no prompt body.
Mock only the subprocess/stream boundary — prove production code paths."""
from __future__ import annotations

from typing import Any

import pytest

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


# ── _load_runner resolves the custom Pi adapter ──────────────────────────

class TestPiRunnerResolution:
    """_load_runner('pi') must return the custom adapter's run function,
    not a descriptor-driven runner."""

    def test_load_runner_resolves_pi_adapter(self) -> None:
        """Prove _load_runner('pi') resolves the hand-written adapter module."""
        from audiagentic.components.providers.services.execution import (
            _load_runner,
        )

        runner = _load_runner("pi")
        assert runner is not None

        # The resolved runner is the run() function from adapters.pi.adapter
        from audiagentic.components.providers.adapters.pi import adapter as pi_adapter

        assert runner is pi_adapter.run

    def test_describe_execution_support_reports_adapter_mode(self) -> None:
        """describe_execution_support('pi') must report 'adapter' mode."""
        from audiagentic.components.providers.services.execution import (
            describe_execution_support,
        )

        info = describe_execution_support("pi")
        assert info["mode"] == "adapter"
        assert "module" in info
        assert "pi.adapter" in info["module"]


# ── adapter.run delivers multiline prompt via stdin ───────────────────────

class TestPiAdapterStdinDelivery:
    """Verify that Pi's run() pipes the full prompt through input_text and
    the command contains no prompt body."""

    @pytest.fixture
    def mock_streaming_command(self, monkeypatch) -> list[dict[str, Any]]:
        """Mock run_streaming_command to capture invocation args.

        Only the subprocess/stream boundary is mocked — all adapter logic
        (command building, sink creation) runs as production code."""
        captured: list[dict[str, Any]] = []

        from audiagentic.components.providers.protocols.streaming.provider_streaming import (  # noqa: F401
            StreamedCommandResult,
        )

        def _capture(command: list[str], *, input_text: str | None = None, **kwargs) -> Any:
            captured.append({
                "command": list(command),
                "input_text": input_text,
            })
            # Return a minimal StreamedCommandResult-like object
            class _Result:
                returncode = 0
                stdout = "ok"
                stderr = ""
            return _Result()

        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.pi.adapter.run_streaming_command",
            _capture,
        )
        return captured

    @pytest.fixture
    def mock_require_executable(self, monkeypatch) -> None:
        """Mock require_executable so the test doesn't need 'pi' on PATH."""
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.pi.adapter.require_executable",
            lambda pid, *aliases: "pi-mock",
        )

    def test_run_passes_multiline_prompt_as_input_text(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
        monkeypatch,
    ) -> None:
        """The Pi adapter's run() passes the full multiline prompt-body as
        input_text to run_streaming_command — not as a CLI argument."""
        from audiagentic.components.providers.adapters.pi import adapter as pi_adapter

        packet_ctx = {
            "provider-id": "pi",
            "model-id": "brutus/coder-quality-mid",
            "prompt-body": MULTILINE_PROMPT,
        }
        provider_cfg: dict[str, Any] = {}

        result = pi_adapter.run(packet_ctx, provider_cfg)
        assert result["status"] == "ok"

        # Verify the invocation captured by our mock
        assert len(mock_streaming_command) == 1
        call = mock_streaming_command[0]

        # The full multiline prompt must be in input_text (not command args)
        assert call["input_text"] is not None
        assert call["input_text"] == MULTILINE_PROMPT

        # Verify embedded newlines are intact
        newline_count = call["input_text"].count("\n")
        assert newline_count >= 1, "Multiline prompt lost its newlines"

    def test_command_contains_no_prompt_body(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
        monkeypatch,
    ) -> None:
        """The command array must NOT contain the prompt body — it goes via
        stdin only (SH21 fix)."""
        from audiagentic.components.providers.adapters.pi import adapter as pi_adapter

        packet_ctx = {
            "provider-id": "pi",
            "model-id": "test-model",
            "prompt-body": MULTILINE_PROMPT,
        }
        provider_cfg: dict[str, Any] = {}

        pi_adapter.run(packet_ctx, provider_cfg)

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
        from audiagentic.components.providers.adapters.pi import adapter as pi_adapter

        packet_ctx = {
            "provider-id": "pi",
            "prompt-body": "Hello",
        }
        provider_cfg: dict[str, Any] = {}

        pi_adapter.run(packet_ctx, provider_cfg)

        command = mock_streaming_command[0]["command"]
        assert command == ["pi-mock", "--print"]
        assert "--model" not in command

    def test_first_newline_preserved_in_input_text(
        self,
        mock_streaming_command: list[dict[str, Any]],
        mock_require_executable: None,
        monkeypatch,
    ) -> None:
        """SH21 regression: the FIRST newline in the prompt must survive.

        When passed as a CLI arg, Pi strips the first newline; via stdin
        pipe (input_text) it is preserved."""
        from audiagentic.components.providers.adapters.pi import adapter as pi_adapter

        prompt_with_critical_first_newline = "Line one\nLine two\nLine three"

        packet_ctx = {
            "provider-id": "pi",
            "prompt-body": prompt_with_critical_first_newline,
        }
        provider_cfg: dict[str, Any] = {}

        pi_adapter.run(packet_ctx, provider_cfg)

        input_text = mock_streaming_command[0]["input_text"]
        assert input_text is not None
        # Exact newline count preserved
        assert input_text.count("\n") == 2, (
            f"Newline count mismatch. Expected 2, got {input_text.count(chr(10))}"
        )
        # First newline boundary preserved
        assert input_text.startswith("Line one\n"), (
            "First newline was lost (SH21 regression)"
        )

    def test_execute_provider_uses_pi_adapter(self, monkeypatch) -> None:
        """Prove the full execution dispatch path uses the Pi adapter.

        execute_provider('pi', ...) → _load_runner('pi') → pi_adapter.run."""
        from audiagentic.components.providers.services.execution import (
            execute_provider,
        )

        # Track if pi_adapter.run was invoked by patching its dependency
        run_called = {"seen": False}
        original_run_streaming = None

        def _track(command: list[str], *, input_text: str | None = None, **kwargs) -> Any:
            run_called["seen"] = True
            class _Result:
                returncode = 0
                stdout = "dispatch-ok"
                stderr = ""
            return _Result()

        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.pi.adapter.run_streaming_command",
            _track,
        )
        monkeypatch.setattr(
            "audiagentic.components.providers.adapters.pi.adapter.require_executable",
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

        assert run_called["seen"], (
            "execute_provider('pi') did not invoke pi_adapter.run"
        )
        assert result["provider-id"] == "pi"
        assert result["status"] == "ok"
