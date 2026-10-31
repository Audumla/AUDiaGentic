"""One-attempt worker supervision for shared gateway dispatch."""
from __future__ import annotations

import logging
import os
import shutil
import site
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerActivityEnvelope,
    WorkerErrorEnvelope,
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
    WorkerHandshakeEnvelope,
    WorkerProcessEvidence,
    WorkerResultEnvelope,
    decode_worker_message,
    encode_worker_message,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import process_creation_identity
from audiagentic.foundation.system.supervised_process import spawn_supervised

if TYPE_CHECKING:
    from audiagentic.components.providers.providers_api import ProviderExecutionResult

logger = logging.getLogger(__name__)


def _wait_for_provider_terminal(
    child: Any,
    input_text: str,
    *,
    on_activity: Callable[[WorkerActivityEnvelope], None] | None = None,
) -> tuple[str, str]:
    """Wait for the provider's terminal frame without inventing failure.

    There is no gateway kill timer (SH22): a remote agent can be legitimately
    quiet while it runs a tool or awaits a remote service. Completion/failure
    authority is the authenticated worker terminal frame, explicit
    cancellation, or later positively correlated death evidence — never
    elapsed time or local CPU.
    """
    # Real supervised children expose streams; consume frames incrementally so
    # activity renewals reach the durable store while a provider is waiting.
    if getattr(child, "stdout", None) is not None and getattr(child, "stdin", None) is not None:
        child.stdin.write(input_text)
        child.stdin.flush()
        child.stdin.close()
        stderr_lines: list[str] = []
        import threading
        stderr_thread = threading.Thread(
            target=lambda: stderr_lines.append(child.stderr.read() or ""), daemon=True
        )
        stderr_thread.start()
        frames: list[str] = []
        for line in iter(child.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            frames.append(line)
            if on_activity is not None:
                try:
                    decoded = decode_worker_message(line)
                    if isinstance(decoded, WorkerActivityEnvelope):
                        on_activity(decoded)
                except Exception:  # noqa: BLE001 - malformed activity cannot end a turn
                    continue
        child.wait()
        stderr_thread.join(timeout=2)
        return "\n".join(frames), "".join(stderr_lines).strip()
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
        # Controlled activity-rig fixture knobs. These remain provider-neutral
        # and are propagated only to the disposable worker process.
        "AUDIAGENTIC_WORKER_ACTIVITY_SOURCES",
        "AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS",
        "AUDIAGENTIC_WORKER_ACTIVITY_STALL_AFTER",
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
    """Best-effort removal of this protected home, not terminal/exit proof."""
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
                    # Deletion is not part of the provider terminal contract.
                    # In particular, raising during context unwind would erase
                    # a valid result or mask the original provider exception.
                    # Retain only this mkdtemp-owned protected directory; never
                    # log its path, exception text, or private contents.
                    logger.warning(
                        "isolated worker private-home cleanup deferred; owned directory retained",
                        extra={"cleanup-deferred": True, "cleanup-reason": "permission-denied"},
                    )
                    break
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
    # Controlled activity-rig fixture knobs are explicitly scoped and copied
    # into disposable workers; no arbitrary caller environment crosses the
    # isolation boundary.
    for name in (
        "AUDIAGENTIC_WORKER_ACTIVITY_SOURCES",
        "AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS",
        "AUDIAGENTIC_WORKER_ACTIVITY_STALL_AFTER",
        "AUDIAGENTIC_ACTIVITY_RIG_PAUSE",
        "AUDIAGENTIC_ACTIVITY_RIG_PAUSE_SECONDS",
        "AUDIAGENTIC_ACTIVITY_RIG_STALL",
        "AUDIAGENTIC_ACTIVITY_RIG_STALL_SECONDS",
    ):
        if name in os.environ:
            environment[name] = os.environ[name]
    if component_profile:
        environment["AUDIAGENTIC_COMPONENT_PROFILE"] = component_profile
    return environment


def _execute_isolated_provider_turn(
    *,
    identity: WorkerExecutionIdentity,
    execution_request: Mapping[str, Any],
    activity_callback: Callable[[WorkerActivityEnvelope], None] | None = None,
    allowed_model_ids: frozenset[str] | None = None,
) -> tuple[ProviderExecutionResult, WorkerExecutionIdentity, WorkerProcessEvidence]:
    """One implementation; observe direct exit after both cleanup contexts."""
    envelope = WorkerExecuteEnvelope(
        identity=identity, execution_request=execution_request
    )
    from audiagentic.components.providers import providers_api

    provider_request = providers_api.ProviderExecutionRequest.from_mapping(
        execution_request
    )
    if (
        allowed_model_ids is not None and provider_request.model_id is not None
        and provider_request.model_id not in allowed_model_ids
    ):
        raise AudiaGenticError(
            "CON-AGW-079", "agents", "prepared model scope excludes the provider execution request", {},
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
                on_activity=activity_callback,
            )
            frames = [line for line in stdout.splitlines() if line]
            if len(frames) < 2:
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
            for activity_frame in frames[1:-1]:
                activity = decode_worker_message(activity_frame)
                if not isinstance(activity, WorkerActivityEnvelope):
                    raise AudiaGenticError(
                        code="CON-AGW-075",
                        kind="agents",
                        message="isolated provider worker emitted a non-terminal frame",
                        details={},
                    )
            terminal = decode_worker_message(frames[-1])
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

            inner = terminal.execution_result
            if (
                inner.get("provider-id") != provider_request.provider_id
                or inner.get("worker-id") != identity.worker_id
                or type(inner.get("attempt-epoch")) is not int
                or inner["attempt-epoch"] != identity.attempt_epoch
            ):
                raise AudiaGenticError(
                    "CON-AGW-079", "agents",
                    "isolated provider result does not match its admitted provider and worker attempt", {},
                )
            if allowed_model_ids is not None and (
                not isinstance(inner.get("model-id"), str) or inner["model-id"] not in allowed_model_ids
            ):
                raise AudiaGenticError(
                    "CON-AGW-079", "agents", "isolated provider result model is outside prepared model scope", {},
                )
            result = providers_api.ProviderExecutionResult.from_mapping(inner)
    # Check the owned process handle AFTER supervision and private-home
    # cleanup. A returned close() is not itself positive exit evidence.
    if allowed_model_ids is not None and child.poll() is None:
        raise AudiaGenticError(
            "CON-AGW-076", "agents", "verified provider worker exit is not observed", {},
        )
    return result, terminal.identity, terminal.process


_VERIFIED_WORKER_KEY = object()


@dataclass(frozen=True, init=False)
class VerifiedWorkerTerminal:
    """Trusted local worker terminal, NOT native acceptance or command authority.

    Only the executor mints this after the existing cleanup contexts exit and
    the direct worker has demonstrably exited. Descendant/job closure is NOT
    proven by SupervisedProcess.close returning: cleanup_proven stays false.
    This evidence alone does not justify fresh-ready node state. A qualifying
    one-shot also needs the node producer's durable terminal write and local
    producer fence/no-other-writer barrier; adapters delegating an active turn
    to a continuing background process do not qualify. Unresolved effects keep
    logical capacity blocked even after an old producer is fenced and its epoch
    rotates. No wire/mapping constructor or public success flag exists;
    command binding and the combined durable barrier belong to the consumer.
    """
    identity: WorkerExecutionIdentity
    process: WorkerProcessEvidence
    result: ProviderExecutionResult = field(repr=False)
    worker_exited: bool = field(default=True, init=False)
    cleanup_proven: bool = field(default=False, init=False)

    def __init__(
        self, *, identity: WorkerExecutionIdentity, process: WorkerProcessEvidence,
        result: ProviderExecutionResult, _key: object = None,
    ) -> None:
        if _key is not _VERIFIED_WORKER_KEY:
            raise TypeError("VerifiedWorkerTerminal is returned only by the trusted worker executor")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "process", process)
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "worker_exited", True)
        object.__setattr__(self, "cleanup_proven", False)


def _freeze_result_data(value: Any) -> Any:
    """Freeze already JSON-validated result data without changing the old API."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_result_data(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_result_data(item) for item in value)
    return value


def execute_isolated_provider_turn(
    *, identity: WorkerExecutionIdentity, execution_request: Mapping[str, Any],
    activity_callback: Callable[[WorkerActivityEnvelope], None] | None = None,
) -> ProviderExecutionResult:
    """Execute one provider request; retain ordinary model-alias behavior."""
    result, _, _ = _execute_isolated_provider_turn(
        identity=identity, execution_request=execution_request,
        activity_callback=activity_callback,
    )
    return result


def execute_verified_isolated_provider_turn(
    *, identity: WorkerExecutionIdentity, execution_request: Mapping[str, Any],
    allowed_model_ids: Collection[str],
    activity_callback: Callable[[WorkerActivityEnvelope], None] | None = None,
) -> VerifiedWorkerTerminal:
    """Return direct-worker terminal evidence after cleanup contexts exit.

    allowed_model_ids MUST come from trusted pre-effect preparation facts.
    Snapshot it before launch; never choose/resolve a model from effect output.
    Direct child exit is explicitly checked; descendant/job closure remains
    unproven (cleanup_proven=False); proof alone is not fresh-ready permission.
    A consumer may combine it with its durable terminal/producer-fencing barrier.
    This adds no spawn path, retry, scheduler or native-acceptance inference.
    """
    if (
        not isinstance(allowed_model_ids, Collection)
        or isinstance(allowed_model_ids, (str, bytes, Mapping)) or not allowed_model_ids
        or any(not isinstance(model, str) or not model for model in allowed_model_ids)
    ):
        raise AudiaGenticError(
            "CON-AGW-079", "agents", "verified execution requires prepared allowed model identities", {},
        )
    prepared_models = frozenset(allowed_model_ids)
    result, accepted_identity, process = _execute_isolated_provider_turn(
        identity=identity, execution_request=execution_request,
        activity_callback=activity_callback, allowed_model_ids=prepared_models,
    )
    # Both context managers exited. A raised cleanup error prevents evidence,
    # but a silent best-effort teardown cannot prove descendant/job closure.
    frozen_result = replace(result, result_data=_freeze_result_data(result.result_data))
    return VerifiedWorkerTerminal(
        identity=accepted_identity, process=process, result=frozen_result, _key=_VERIFIED_WORKER_KEY,
    )


__all__ = ["execute_isolated_provider_turn", "execute_verified_isolated_provider_turn", "VerifiedWorkerTerminal"]
