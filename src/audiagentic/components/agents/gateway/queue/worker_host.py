"""Disposable process entry point for one isolated provider turn."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path

from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerActivityEnvelope,
    WorkerErrorEnvelope,
    WorkerExecuteEnvelope,
    WorkerHandshakeEnvelope,
    WorkerProcessEvidence,
    WorkerResultEnvelope,
    decode_worker_message,
    encode_worker_message,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import process_creation_identity

_MAX_FRAME_CHARS = 8 * 1024 * 1024
# Bounded diagnostic payload: enough for a useful traceback, small enough to
# prevent an OOM attack via unbounded error reporting.
_MAX_DIAGNOSTIC_BYTES = 64 * 1024
_PROTOCOL_OUT = sys.stdout


_WRITE_LOCK = threading.Lock()


def _provider_activity_path(execution_request: dict[str, object]) -> Path | None:
    """Resolve the private normalized-event file for one worker attempt.

    Provider stream sinks write bounded, redacted event records under the
    request-owned runtime directory.  The worker relays only the existence of
    a new event (never its text or path) as ``provider-progress`` activity.
    Invalid or escaping job ids simply disable this optional observation seam.
    """
    packet = execution_request.get("packet-data")
    if not isinstance(packet, dict):
        return None
    job_id = packet.get("job-id") or packet.get("request-id")
    root_value = execution_request.get("project-root")
    if not isinstance(job_id, str) or not job_id or not isinstance(root_value, str):
        return None
    try:
        root = Path(root_value).resolve()
        candidate = (root / ".audiagentic" / "runtime" / "jobs" / job_id / "events.ndjson").resolve()
        if not candidate.is_relative_to(root):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _watch_provider_activity(
    path: Path | None,
    stop: threading.Event,
    emit: Callable[[str], None],
) -> None:
    """Relay newly appended normalized stream events without payloads."""
    if path is None:
        return
    try:
        # Retries reuse the request id and therefore the runtime directory;
        # do not replay a prior attempt's events as fresh activity.
        offset = path.stat().st_size
    except (FileNotFoundError, OSError):
        offset = 0
    last_emit = 0.0
    while not stop.wait(0.1):
        try:
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                lines = handle.readlines()
                offset = handle.tell()
        except (FileNotFoundError, OSError):
            continue
        saw_event = False
        for line in lines:
            if stop.is_set():
                return
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(event, dict) and event.get("event-kind"):
                saw_event = True
        # Match the gateway's normal activity relay cadence.  Provider output
        # can be extremely chatty; one bounded renewal per second is enough to
        # prove liveness without turning every output line into a durable write.
        now = time.monotonic()
        if saw_event and now - last_emit >= 1.0:
            emit("provider-progress")
            last_emit = now


def _write(message: object) -> None:
    with _WRITE_LOCK:
        _PROTOCOL_OUT.write(encode_worker_message(message) + "\n")  # type: ignore[arg-type]
        _PROTOCOL_OUT.flush()


def _safe_error(
    request: WorkerExecuteEnvelope,
    evidence: WorkerProcessEvidence,
    exc: AudiaGenticError,
) -> WorkerErrorEnvelope:
    try:
        return WorkerErrorEnvelope(
            identity=request.identity,
            process=evidence,
            error_code=exc.code,
            error_kind=exc.kind,
            message=exc.message,
        )
    except AudiaGenticError:
        return WorkerErrorEnvelope(
            identity=request.identity,
            process=evidence,
            error_code="INT-AGW-076",
            error_kind="agents",
            message="isolated provider execution failed",
        )


def _emit_worker_diagnostic(exc: Exception) -> None:
    """Write a bounded, redacted diagnostic to operator-only stderr.

    The worker protocol pipe (stdout) must never carry raw traceback data;
    this function writes a redacted diagnostic to stderr for the operator.
    The payload is bounded at _MAX_DIAGNOSTIC_BYTES to prevent unbounded
    error-reporting amplification.
    """
    diagnostic_lines: list[str] = [
        f"WORKER-EXCEPTION: {type(exc).__name__}: {exc}",
    ]
    tb_text = traceback.format_exception(type(exc), exc, exc.__traceback__)
    # Bounded truncation: keep the head of the traceback (most actionable)
    raw = "".join(tb_text)
    if len(raw) > _MAX_DIAGNOSTIC_BYTES:
        raw = raw[:_MAX_DIAGNOSTIC_BYTES]
        diagnostic_lines.append("<truncated-diagnostic>")
    diagnostic_lines.append(raw)
    # Write to stderr (operator channel, never crosses the protocol pipe).
    try:
        sys.stderr.write("\n".join(diagnostic_lines) + "\n")
        sys.stderr.flush()
    except OSError:
        pass  # stderr may be unavailable in some environments


def main() -> int:
    frame = sys.stdin.readline(_MAX_FRAME_CHARS + 1)
    if not frame or len(frame) > _MAX_FRAME_CHARS:
        return 2
    request: WorkerExecuteEnvelope | None = None
    evidence: WorkerProcessEvidence | None = None
    try:
        decoded = decode_worker_message(frame)
        if not isinstance(decoded, WorkerExecuteEnvelope):
            return 2
        request = decoded
        identity = request.identity

        # The supervisor already supplies these process-start facts. Repeat
        # them before importing the provider public API so component discovery
        # cannot observe a different root/profile.
        os.chdir(identity.project_root)
        if identity.component_profile:
            os.environ["AUDIAGENTIC_COMPONENT_PROFILE"] = identity.component_profile
        else:
            os.environ.pop("AUDIAGENTIC_COMPONENT_PROFILE", None)

        creation_identity = process_creation_identity(os.getpid())
        if not creation_identity:
            return 3
        evidence = WorkerProcessEvidence(
            pid=os.getpid(),
            process_creation_identity=creation_identity,
            working_directory=str(Path.cwd().resolve()),
        )
        if evidence.working_directory != identity.project_root:
            return 4
        _write(WorkerHandshakeEnvelope(identity=identity, process=evidence))

        if identity.provider_isolation_tier != "full-isolation":
            raise AudiaGenticError(
                code="UNS-AGW-076",
                kind="agents",
                message="provider isolation tier is not safe for concurrent gateway execution",
                details={"provider-isolation-tier": identity.provider_isolation_tier},
            )

        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        activity_thread: threading.Thread | None = None
        sequence = 0
        sequence_lock = threading.Lock()
        # A provider may opt into richer progress vocabulary through the
        # authenticated worker boundary.  The default remains heartbeat;
        # test rigs can deterministically exercise provider/tool progress by
        # setting this process-local fixture knob.
        activity_sources = tuple(
            source.strip()
            for source in os.environ.get("AUDIAGENTIC_WORKER_ACTIVITY_SOURCES", "worker-heartbeat").split(",")
            if source.strip()
        ) or ("worker-heartbeat",)
        try:
            activity_interval = max(
                0.05, float(os.environ.get("AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS", "5"))
            )
        except ValueError:
            activity_interval = 5.0
        try:
            stall_after = int(os.environ.get("AUDIAGENTIC_WORKER_ACTIVITY_STALL_AFTER", "0"))
        except ValueError:
            stall_after = 0

        def emit_frame(source: str) -> None:
            nonlocal sequence
            with sequence_lock:
                sequence += 1
                current = sequence
            if stall_after > 0 and current > stall_after:
                return
            _write(WorkerActivityEnvelope(identity, evidence, current, source))

        def emit_heartbeat() -> None:
            while not heartbeat_stop.wait(activity_interval):
                source = activity_sources[(sequence % len(activity_sources))]
                emit_frame(source)

        heartbeat_thread = threading.Thread(target=emit_heartbeat, name="worker-activity", daemon=True)
        heartbeat_thread.start()
        activity_thread = threading.Thread(
            target=_watch_provider_activity,
            args=(_provider_activity_path(request.execution_request), heartbeat_stop, lambda source: emit_frame(source)),
            name="provider-activity",
            daemon=True,
        )
        activity_thread.start()
        # The pipe is a protocol-only channel. Provider libraries occasionally
        # print progress directly. Import and execute them with stdout pointed
        # at the discarded stderr channel so ConsoleSink's import-time default
        # cannot corrupt the framed response either.
        try:
            with redirect_stdout(sys.stderr):
            # Import only after root/profile initialization. Providers owns
            # config/model/secret resolution and adapter invocation behind its
            # public boundary.
                from audiagentic.components.providers import providers_api

                provider_request = providers_api.ProviderExecutionRequest.from_mapping(
                    request.execution_request
                )
                result = providers_api.execute_provider_turn(provider_request)
            # Freeze the activity stream before publishing the terminal frame.
            # Otherwise a watcher tick racing with this write can append an
            # activity frame after the result and make the parent reject the
            # otherwise valid worker response ordering.
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join()
            if activity_thread is not None:
                activity_thread.join()
            _write(
                WorkerResultEnvelope(
                    identity=identity,
                    process=evidence,
                    execution_result=result.to_mapping(),
                )
            )
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)
            if activity_thread is not None:
                activity_thread.join(timeout=1)
        return 0
    except AudiaGenticError as exc:
        if request is not None and evidence is not None:
            _write(_safe_error(request, evidence, exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - raw worker failures never cross the pipe
        _emit_worker_diagnostic(exc)
        if request is not None and evidence is not None:
            _write(
                WorkerErrorEnvelope(
                    identity=request.identity,
                    process=evidence,
                    error_code="INT-AGW-076",
                    error_kind="agents",
                    message="isolated provider worker failed unexpectedly",
                )
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
