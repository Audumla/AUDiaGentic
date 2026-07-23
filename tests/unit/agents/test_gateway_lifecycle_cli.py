"""SH10 Slice A — CLI wiring for gateway lifecycle operations.

Tests cover:
- Each HTTP-delegated command (status/drain/resume/stop) dispatches exactly once
  through the standalone gateway client and prints redacted JSON.
- ``--force`` flag forwarding on ``gateway stop``.
- ``gateway recover`` bypassing HTTP entirely and invoking the record-only
  helper directly.
- Busy graceful stop surfacing the existing conflict error (no force).
- No lifecycle-state mutation in CLI handlers (no ManagedServiceStore, no
  transition calls, no signal logic).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure src is on path for standalone execution
_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class FakeStandaloneClient:
    """Minimal StandaloneGatewayClient mock recording calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def close(self) -> None:
        pass

    def service_status(self, project_root: Path) -> dict:
        self.calls.append(("service_status", {}))
        return {"state": "running", "ok": True}

    def service_drain(self, project_root: Path) -> dict:
        self.calls.append(("service_drain", {}))
        return {"state": "draining", "ok": True}

    def service_resume(self, project_root: Path) -> dict:
        self.calls.append(("service_resume", {}))
        return {"state": "running", "ok": True}

    def service_stop(self, project_root: Path, *, force: bool = False) -> dict:
        self.calls.append(("service_stop", {"force": force}))
        if not force:
            # Simulate busy gateway refusing graceful stop
            from audiagentic.components.agents.agents_gateway_lifecycle import (
                lifecycle_conflict_error,
            )
            raise lifecycle_conflict_error(
                1,
                "gateway is not quiescent; drain first or use force",
                quiescence={"quiescent": False},
                other_active_leases=1,
            )
        return {"stopping": True, "forced": force, "affected-work": {}}


class FakeRecoverUnprovable:
    """Mock recover_unprovable_owner recording calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(
        self,
        *,
        service_root: Path | None = None,
        confirm: bool = False,
        reason: str | None = None,
    ) -> dict:
        self.calls.append({"service_root": service_root, "confirm": confirm, "reason": reason})
        if not confirm:
            from audiagentic.components.agents.agents_gateway_lifecycle import (
                lifecycle_validation_error,
            )
            raise lifecycle_validation_error(
                4,
                "unprovable-owner recovery mutates the durable record; pass confirm=true",
                recorded_pid=None,
                observed_alive=False,
            )
        return {
            "recovered": True,
            "state": "failed",
            "owner-epoch": "epoch-123",
            "diagnostics": {"failure-class": "unprovable-owner-recovered"},
        }


# ── HTTP-delegated commands (status / drain / resume / stop) ─────────

def _set_env(tmp_path: Path, endpoint: str = "http://127.0.0.1:9999") -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("test-token-abc")
    os.environ["AUDIAGENTIC_GATEWAY_ENDPOINT"] = endpoint
    os.environ["AUDIAGENTIC_GATEWAY_TOKEN_FILE"] = str(token_file)


@pytest.fixture(autouse=True)
def _env_cleanup() -> None:
    yield
    for key in ("AUDIAGENTIC_GATEWAY_ENDPOINT", "AUDIAGENTIC_GATEWAY_TOKEN_FILE"):
        os.environ.pop(key, None)


class TestGatewayStatus:
    def test_status_delegates_once_via_http(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _set_env(tmp_path)
        fake = FakeStandaloneClient()

        from audiagentic.commands.gateway import cmd_gateway_status
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            return_value=fake,
        ):
            rc = cmd_gateway_status(mock.MagicMock(), tmp_path)

        assert rc == 0
        assert fake.calls == [("service_status", {})]
        out = json.loads(capsys.readouterr().out)
        assert out["state"] == "running"


class TestGatewayDrain:
    def test_drain_delegates_once_via_http(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _set_env(tmp_path)
        fake = FakeStandaloneClient()

        from audiagentic.commands.gateway import cmd_gateway_drain
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            return_value=fake,
        ):
            rc = cmd_gateway_drain(mock.MagicMock(), tmp_path)

        assert rc == 0
        assert fake.calls == [("service_drain", {})]
        out = json.loads(capsys.readouterr().out)
        assert out["state"] == "draining"


class TestGatewayResume:
    def test_resume_delegates_once_via_http(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _set_env(tmp_path)
        fake = FakeStandaloneClient()

        from audiagentic.commands.gateway import cmd_gateway_resume
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            return_value=fake,
        ):
            rc = cmd_gateway_resume(mock.MagicMock(), tmp_path)

        assert rc == 0
        assert fake.calls == [("service_resume", {})]
        out = json.loads(capsys.readouterr().out)
        assert out["state"] == "running"


class TestGatewayStop:
    def test_stop_force_forwarded_via_http(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--force flag must be forwarded to service_stop(force=True)."""
        _set_env(tmp_path)
        fake = FakeStandaloneClient()

        from audiagentic.commands.gateway import cmd_gateway_stop
        args = mock.MagicMock(force=True)
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            return_value=fake,
        ):
            rc = cmd_gateway_stop(args, tmp_path)

        assert rc == 0
        assert fake.calls == [("service_stop", {"force": True})]
        out = json.loads(capsys.readouterr().out)
        assert out["stopping"] is True

    def test_stop_no_force_delegates_with_force_false(self, tmp_path: Path) -> None:
        """Graceful stop (no --force) must send force=False."""
        _set_env(tmp_path)
        fake = FakeStandaloneClient()

        from audiagentic.commands.gateway import cmd_gateway_stop
        args = mock.MagicMock(force=False)
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            return_value=fake,
        ):
            from audiagentic.foundation.contracts.errors import AudiaGenticError
            with pytest.raises(AudiaGenticError):
                cmd_gateway_stop(args, tmp_path)

        # force=False must be forwarded; busy gateway raises CON-AGLC-001
        assert fake.calls == [("service_stop", {"force": False})]


class TestGatewayRecover:
    def test_recover_bypasses_http_calls_helper_directly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """recover must NOT use StandaloneGatewayClient; it invokes the
        record-only helper directly (the service may be dead)."""
        _set_env(tmp_path)  # env set but should be ignored
        fake_recover = FakeRecoverUnprovable()

        from audiagentic.commands.gateway import cmd_gateway_recover
        from audiagentic.components.agents import agents_gateway_lifecycle as lc_mod

        args = mock.MagicMock(confirm=True, reason="stale-owner")
        with mock.patch.object(lc_mod, "recover_unprovable_owner", fake_recover):
            rc = cmd_gateway_recover(args, tmp_path)

        assert rc == 0
        assert fake_recover.calls == [{"service_root": tmp_path, "confirm": True, "reason": "stale-owner"}]
        out = json.loads(capsys.readouterr().out)
        assert out["recovered"] is True
        assert out["diagnostics"]["failure-class"] == "unprovable-owner-recovered"

    def test_recover_without_confirm_raises(
        self, tmp_path: Path
    ) -> None:
        """Recovery without --confirm must be rejected (record-only safety)."""
        _set_env(tmp_path)
        fake_recover = FakeRecoverUnprovable()

        from audiagentic.commands.gateway import cmd_gateway_recover
        from audiagentic.components.agents import agents_gateway_lifecycle as lc_mod
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        args = mock.MagicMock(confirm=False, reason=None)
        with mock.patch.object(lc_mod, "recover_unprovable_owner", fake_recover):
            with pytest.raises(AudiaGenticError):
                cmd_gateway_recover(args, tmp_path)

    def test_recover_no_http_client_used(
        self, tmp_path: Path
    ) -> None:
        """Even if env is set for standalone mode, recover must not create an HTTP client."""
        _set_env(tmp_path)
        fake_recover = FakeRecoverUnprovable()

        from audiagentic.commands.gateway import cmd_gateway_recover
        from audiagentic.components.agents import agents_gateway_lifecycle as lc_mod
        args = mock.MagicMock(confirm=True, reason="test")
        with mock.patch(
            "audiagentic.components.agents.agents_gateway_remote_client.StandaloneGatewayClient",
            side_effect=AssertionError("HTTP client created!"),
        ):
            with mock.patch.object(lc_mod, "recover_unprovable_owner", fake_recover):
                rc = cmd_gateway_recover(args, tmp_path)

        assert rc == 0

    def test_recover_reason_forwarded(
        self, tmp_path: Path
    ) -> None:
        """--reason must be forwarded to the recovery helper."""
        _set_env(tmp_path)
        fake_recover = FakeRecoverUnprovable()

        from audiagentic.commands.gateway import cmd_gateway_recover
        from audiagentic.components.agents import agents_gateway_lifecycle as lc_mod

        args = mock.MagicMock(confirm=True, reason="operator-confirmed unprovable owner")
        with mock.patch.object(lc_mod, "recover_unprovable_owner", fake_recover):
            cmd_gateway_recover(args, tmp_path)

        assert fake_recover.calls[-1]["reason"] == "operator-confirmed unprovable owner"


# ── Architecture: no lifecycle-state mutation in CLI handlers ───────

class TestNoLifecycleMutationInCli:
    """CLI handlers must not directly instantiate ManagedServiceStore,
    call transition(), acquire_lease(), or any other lifecycle internal."""

    FORBIDDEN_SYMBOLS = [
        "ManagedServiceStore(",
        "acquire_lease(",
        ".transition(",
        "ManagedServiceShutdown",
        "kill_process_tree",
        "signal_owned_process",
    ]

    def test_gateway_cli_has_no_lifecycle_internals(self) -> None:
        cli_module_path = _SRC / "audiagentic" / "commands" / "gateway.py"
        source = cli_module_path.read_text(encoding="utf-8")
        hits = [s for s in self.FORBIDDEN_SYMBOLS if s in source]
        assert not hits, f"gateway CLI handler reaches lifecycle internals: {hits}"

    def test_gateway_cli_no_lifecycle_import(self) -> None:
        """The CLI module must not import from agents_gateway_lifecycle
        except recover_unprovable_owner (used by recover command)."""
        cli_module_path = _SRC / "audiagentic" / "commands" / "gateway.py"
        source = cli_module_path.read_text(encoding="utf-8")

        # The only allowed lifecycle import is recover_unprovable_owner
        assert "from audiagentic.components.agents.agents_gateway_lifecycle import" in source
        # But no other lifecycle symbols should be imported
        assert "GatewayLifecycleController" not in source
        assert "gateway_quiescence_facts" not in source
        assert "ManagedServiceStore" not in source


# ── Launcher wiring: subcommand dispatch ─────────────────────────────

class TestLauncherWiring:
    """The launcher must dispatch gateway lifecycle sub-commands through
    the _GATEWAY_LIFECYCLE_HANDLERS registry."""

    def test_gateway_lifecycle_handlers_registered(self) -> None:
        from audiagentic.launcher import _GATEWAY_LIFECYCLE_HANDLERS

        assert "status" in _GATEWAY_LIFECYCLE_HANDLERS
        assert "drain" in _GATEWAY_LIFECYCLE_HANDLERS
        assert "resume" in _GATEWAY_LIFECYCLE_HANDLERS
        assert "stop" in _GATEWAY_LIFECYCLE_HANDLERS
        assert "recover" in _GATEWAY_LIFECYCLE_HANDLERS

    def test_serve_still_in_main_registry(self) -> None:
        """The 'serve' sub-command still goes through the main cmd_gateway handler."""
        from audiagentic.launcher import _COMMAND_HANDLERS
        from audiagentic.launcher import cmd_gateway as gateway_cmd

        assert "gateway" in _COMMAND_HANDLERS
        assert _COMMAND_HANDLERS["gateway"] is gateway_cmd


# ── E2E launcher dispatch (subprocess) ────────────────────────────

class TestLauncherDispatch:
    """Ensure the launcher parses and dispatches gateway lifecycle commands."""

    def test_gateway_status_parses(self, tmp_path: Path) -> None:
        """The 'gateway status' subcommand must parse without error."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "audiagentic.launcher", "gateway", "status"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
        # We expect a SystemExit from _standalone_client_from_env (missing env vars),
        # NOT an argparse error.
        assert "unrecognized arguments" not in result.stderr
        assert "unsupported gateway command" not in result.stderr

    def test_gateway_stop_with_force_parses(self, tmp_path: Path) -> None:
        """The 'gateway stop --force' subcommand must parse without error."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "audiagentic.launcher", "gateway", "stop", "--force"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
        assert "unrecognized arguments" not in result.stderr
        assert "unsupported gateway command" not in result.stderr

    def test_gateway_recover_with_flags_parses(self, tmp_path: Path) -> None:
        """The 'gateway recover --confirm --reason TEXT' must parse without error."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "audiagentic.launcher", "gateway", "recover", "--confirm", "--reason", "test"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(_SRC)},
        )
        assert "unrecognized arguments" not in result.stderr

    def test_gateway_serve_still_works(self, tmp_path: Path) -> None:
        """The existing 'gateway serve' must still parse and dispatch correctly."""
        import subprocess

        # serve will actually start; we just check it parses (no argparse error)
        proc = subprocess.Popen(
            [sys.executable, '-m', 'audiagentic.launcher', 'gateway', 'serve'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(tmp_path),
            env={**os.environ, 'PYTHONPATH': str(_SRC)},
        )
        try:
            _stdout, _stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            # Expected: serve runs indefinitely; kill it
            proc.kill()
            _stdout, _stderr = proc.communicate()
        assert 'unrecognized arguments' not in _stderr
