"""One-attempt worker supervision for shared gateway dispatch."""
from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerErrorEnvelope,
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
    WorkerHandshakeEnvelope,
    WorkerResultEnvelope,
    decode_worker_message,
    encode_worker_message,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import (
    process_cpu_time_seconds,
    process_creation_identity,
)
from audiagentic.foundation.system.supervised_process import spawn_supervised

# SH22: replace a single wall-clock kill with an activity-verified watchdog.
# `timeout_seconds` (the caller's own number) becomes a grace period, not an
# immediate kill -- a worker still genuinely consuming CPU past it is given
# more room, up to this absolute ceiling, matching the operational policy
# already adopted for delegated coding/review work (SH22 step 0).
_ABSOLUTE_SAFETY_CEILING_SECONDS = 2700.0
_STALL_POLL_INTERVAL_SECONDS = 2.0
# Consecutive flat-CPU polls after timeout_seconds elapses before a stall is
# considered verified rather than a transient scheduling gap.
_STALL_GRACE_POLLS = 2


class _WatchdogStall(Exception):
    """Internal signal: the watchdog verified a stall or hit the absolute
    ceiling and is killing the child. Never crosses execute_isolated_provider_turn's
    boundary -- translated to AudiaGenticError there."""

    def __init__(self, classification: str, *, elapsed_seconds: float) -> None:
        self.classification = classification
        self.elapsed_seconds = elapsed_seconds
        super().__init__(classification)


def _wait_with_activity_watchdog(
    child: Any,
    input_text: str,
    *,
    timeout_seconds: float,
) -> tuple[str, str]:
    """Wait for the child to complete without killing merely-slow-but-active
    work at a fixed wall-clock line (SH22).

    Runs the actual read/write in a background thread (communicate() already
    handles the write-while-draining-stdout-and-stderr deadlock avoidance
    correctly; reimplementing that by hand here would be a real bug risk for
    no benefit) while the calling thread polls process CPU-time deltas as
    the activity signal. A verified stall (flat CPU for `_STALL_GRACE_POLLS`
    consecutive polls once `timeout_seconds` has elapsed) or the absolute
    ceiling raises `_WatchdogStall`; a naturally-exiting child, however long
    that took short of the ceiling, never does.
    """
    comm_result: dict[str, str] = {}
    comm_error: dict[str, BaseException] = {}

    def _communicate() -> None:
        try:
            stdout, stderr = child.communicate(input_text)
            comm_result["stdout"] = stdout
            comm_result["stderr"] = (stderr or "").strip()
        except BaseException as exc:  # noqa: BLE001 - relayed to the polling loop below
            comm_error["exc"] = exc

    comm_thread = threading.Thread(target=_communicate, daemon=True)
    comm_thread.start()

    started_at = time.monotonic()
    last_cpu_time = process_cpu_time_seconds(child.pid)
    flat_polls = 0

    while comm_thread.is_alive():
        comm_thread.join(timeout=_STALL_POLL_INTERVAL_SECONDS)
        if not comm_thread.is_alive():
            break
        elapsed = time.monotonic() - started_at
        if elapsed >= _ABSOLUTE_SAFETY_CEILING_SECONDS:
            raise _WatchdogStall("absolute-safety-ceiling", elapsed_seconds=elapsed)
        if elapsed < timeout_seconds:
            continue
        current_cpu_time = process_cpu_time_seconds(child.pid)
        if current_cpu_time is None:
            # Facts became unreadable (e.g. exited between checks) -- let
            # the next join() observe the real state rather than guess.
            continue
        if last_cpu_time is not None and current_cpu_time > last_cpu_time + 0.01:
            flat_polls = 0
        else:
            flat_polls += 1
        last_cpu_time = current_cpu_time
        if flat_polls >= _STALL_GRACE_POLLS:
            raise _WatchdogStall("verified-stall", elapsed_seconds=elapsed)

    if "exc" in comm_error:
        raise comm_error["exc"]
    return comm_result["stdout"], comm_result["stderr"]

_PASSTHROUGH_ENV = frozenset(
    {
        "COMSPEC",
        "LANG",
        "NODE_EXTRA_CA_CERTS",
        "PATH",
        "PATHEXT",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TERM",
        "WINDIR",
    }
)
_PROTECTED_WORKER_ENV = frozenset(
    {
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "TMP",
        "TEMP",
        "PYTHONPATH",
        "PI_CODING_AGENT_DIR",
        "PI_CODING_AGENT_SESSION_DIR",
    }
)


@contextmanager
def _private_worker_home() -> Iterator[Path]:
    """Remove a private home after OS process-tree termination settles."""
    path = Path(tempfile.mkdtemp(prefix="audiagentic-worker-"))
    try:
        yield path
    finally:
        deadline = time.monotonic() + 5
        while True:
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)


def _replacement_environment(component_profile: str, private_home: Path) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _PASSTHROUGH_ENV or name.upper().startswith("LC_")
    }
    pi_agent_dir = private_home / ".pi" / "agent"
    pi_agent_dir.mkdir(parents=True, exist_ok=True)
    # Preserve the managed Pi model registry without copying the caller's
    # extensions, sessions, or other mutable agent state into the worker.
    source_pi_dir = os.environ.get("PI_CODING_AGENT_DIR")
    source_models = (
        Path(source_pi_dir) / "models.json"
        if source_pi_dir
        else Path.home() / ".pi" / "agent" / "models.json"
    )
    if source_models.is_file():
        shutil.copy2(source_models, pi_agent_dir / "models.json")

    environment.update(
        {
            "HOME": str(private_home),
            "USERPROFILE": str(private_home),
            "XDG_CONFIG_HOME": str(private_home / ".config"),
            "TMP": str(private_home / "tmp"),
            "TEMP": str(private_home / "tmp"),
            # Pi otherwise inherits a caller-scoped PI_CODING_AGENT_DIR and
            # discovers extensions/configuration outside this worker home.
            "PI_CODING_AGENT_DIR": str(pi_agent_dir),
            "PI_CODING_AGENT_SESSION_DIR": str(
                private_home / ".pi" / "sessions"
            ),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if component_profile:
        environment["AUDIAGENTIC_COMPONENT_PROFILE"] = component_profile
    return environment


def execute_isolated_provider_turn(
    *,
    identity: WorkerExecutionIdentity,
    execution_request: Mapping[str, Any],
    timeout_seconds: float,
) -> Any:
    """Execute one MA17 provider request in a disposable owned process."""
    envelope = WorkerExecuteEnvelope(
        identity=identity, execution_request=execution_request
    )
    from audiagentic.components.providers import providers_api

    provider_request = providers_api.ProviderExecutionRequest.from_mapping(
        execution_request
    )
    provider_environment = providers_api.prepare_provider_execution_environment(
        provider_request
    )
    if any(name.upper() in _PROTECTED_WORKER_ENV for name in provider_environment):
        raise AudiaGenticError(
            code="CON-AGW-080",
            kind="agents",
            message="provider execution environment attempted to replace worker isolation",
        )
    with _private_worker_home() as private_home:
        (private_home / "tmp").mkdir()
        environment = _replacement_environment(identity.component_profile, private_home)
        environment.update(provider_environment)
        # Launching the base interpreter avoids the Windows venv redirector's
        # PID hand-off, but it must still import the current trusted runtime.
        # Supply only repository/venv-owned import roots, never the caller's
        # arbitrary PYTHONPATH.
        trusted_import_roots = [
            str(Path(__file__).resolve().parents[5]),
            *(str(Path(root).resolve()) for root in site.getsitepackages()),
        ]
        environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(trusted_import_roots))
        # The Windows venv redirector may hand execution to the base
        # interpreter under a different PID. Process ownership evidence must
        # describe the process that performs the worker handshake, so launch
        # that stable interpreter directly (the same rule used by managed
        # service lifecycle tests). Other platforms keep sys.executable.
        worker_python = (
            getattr(sys, "_base_executable", sys.executable)
            if os.name == "nt"
            else sys.executable
        )
        command = [
            worker_python,
            "-m",
            "audiagentic.components.agents.gateway.queue.worker_host",
        ]
        with spawn_supervised(
            command,
            cwd=identity.project_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            isolated_process_group=True,
        ) as child:
            expected_creation = process_creation_identity(child.pid)
            if not expected_creation:
                raise AudiaGenticError(
                    code="CON-AGW-076",
                    kind="agents",
                    message="isolated provider worker creation evidence is unavailable",
                )
            try:
                # stderr_text is a string (spawn_supervised uses text=True);
                # the worker writes bounded traceback data here on unexpected
                # exceptions.
                stdout, stderr_text = _wait_with_activity_watchdog(
                    child,
                    encode_worker_message(envelope) + "\n",
                    timeout_seconds=timeout_seconds,
                )
            except _WatchdogStall as exc:
                message = (
                    "isolated provider worker exceeded its absolute safety ceiling"
                    if exc.classification == "absolute-safety-ceiling"
                    else "isolated provider worker exceeded its execution timeout"
                )
                raise AudiaGenticError(
                    code="TO-AGW-076",
                    kind="agents",
                    message=message,
                    details={
                        "worker-id": identity.worker_id,
                        "watchdog-classification": exc.classification,
                        "requested-timeout-seconds": timeout_seconds,
                        "elapsed-seconds": round(exc.elapsed_seconds, 1),
                    },
                ) from exc

            frames = [line for line in stdout.splitlines() if line]
            if len(frames) != 2:
                raise AudiaGenticError(
                    code="INT-AGW-077",
                    kind="agents",
                    message="isolated provider worker returned an invalid response sequence",
                    details={
                        "worker-id": identity.worker_id,
                        "frame-count": len(frames),
                        "returncode": child.poll(),
                    },
                )
            handshake = decode_worker_message(frames[0])
            terminal = decode_worker_message(frames[1])
            if not isinstance(handshake, WorkerHandshakeEnvelope):
                raise AudiaGenticError(
                    code="CON-AGW-075",
                    kind="agents",
                    message="isolated provider worker did not complete its identity handshake",
                )
            if (
                handshake.identity != identity
                or handshake.process.pid != child.pid
                or handshake.process.process_creation_identity != expected_creation
                or handshake.process.working_directory != identity.project_root
            ):
                raise AudiaGenticError(
                    code="CON-AGW-076",
                    kind="agents",
                    message="isolated provider worker identity evidence does not match its process",
                )
            if isinstance(terminal, WorkerErrorEnvelope):
                if terminal.identity != identity or terminal.process != handshake.process:
                    raise AudiaGenticError(
                        code="CON-AGW-077",
                        kind="agents",
                        message="isolated provider worker error identity does not match its handshake",
                    )
                error_details: dict[str, object] = {
                    "worker-id": identity.worker_id,
                }
                # INT-AGW-076 means the worker had an unexpected exception;
                # include a bounded redacted diagnostic from stderr so the
                # operator has an actionable reference.
                if terminal.error_code == "INT-AGW-076" and stderr_text:
                    _DIAGNOSTIC_MAX = 2 * 1024  # 2 KB bounded diagnostic in error details
                    diag = stderr_text[:_DIAGNOSTIC_MAX]
                    if len(stderr_text) > _DIAGNOSTIC_MAX:
                        diag += "\n<truncated>"
                    error_details["worker-diagnostic"] = diag
                raise AudiaGenticError(
                    code=terminal.error_code,
                    kind=terminal.error_kind,
                    message=terminal.message,
                    details=error_details,
                )
            if not isinstance(terminal, WorkerResultEnvelope):
                raise AudiaGenticError(
                    code="CON-AGW-078",
                    kind="agents",
                    message="isolated provider worker returned an unsupported terminal response",
                )
            if terminal.identity != identity or terminal.process != handshake.process:
                raise AudiaGenticError(
                    code="CON-AGW-079",
                    kind="agents",
                    message="isolated provider worker result identity does not match its handshake",
                )
            from audiagentic.components.providers import providers_api

            return providers_api.ProviderExecutionResult.from_mapping(
                terminal.execution_result
            )


__all__ = ["execute_isolated_provider_turn"]
