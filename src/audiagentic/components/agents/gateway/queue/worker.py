"""One-attempt worker supervision for shared gateway dispatch."""
from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
import tempfile
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
from audiagentic.foundation.system.managed_process import process_creation_identity
from audiagentic.foundation.system.supervised_process import spawn_supervised


def _wait_for_provider_terminal(
    child: Any,
    input_text: str,
    *,
    timeout_seconds: float,
) -> tuple[str, str]:
    """Wait for the provider's terminal frame without inventing failure.

    ``timeout_seconds`` remains part of the execution request for a provider
    that has an explicit, provider-owned deadline.  It is deliberately not a
    gateway kill timer: a remote agent can be legitimately quiet while it
    runs a tool or awaits a remote service.  Completion/failure authority is
    the authenticated worker terminal frame, explicit cancellation, or later
    positively correlated death evidence — never elapsed time or local CPU.
    """
    del timeout_seconds
    stdout, stderr = child.communicate(input_text)
    return stdout, (stderr or "").strip()

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
            # stderr_text is a string (spawn_supervised uses text=True);
            # the worker writes bounded traceback data here on unexpected
            # exceptions.
            stdout, stderr_text = _wait_for_provider_terminal(
                child,
                encode_worker_message(envelope) + "\n",
                timeout_seconds=timeout_seconds,
            )
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
