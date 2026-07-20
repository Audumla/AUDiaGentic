"""Disposable process entry point for one isolated provider turn."""
from __future__ import annotations

import os
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from audiagentic.components.agents.contracts.worker_protocol import (
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


def _write(message: object) -> None:
    sys.stdout.write(encode_worker_message(message) + "\n")  # type: ignore[arg-type]
    sys.stdout.flush()


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

        # The pipe is a protocol-only channel. Provider libraries occasionally
        # print progress directly. Import and execute them with stdout pointed
        # at the discarded stderr channel so ConsoleSink's import-time default
        # cannot corrupt the framed response either.
        with redirect_stdout(sys.stderr):
            # Import only after root/profile initialization. Providers owns
            # config/model/secret resolution and adapter invocation behind its
            # public boundary.
            from audiagentic.components.providers import providers_api

            provider_request = providers_api.ProviderExecutionRequest.from_mapping(
                request.execution_request
            )
            result = providers_api.execute_provider_turn(provider_request)
        _write(
            WorkerResultEnvelope(
                identity=identity,
                process=evidence,
                execution_result=result.to_mapping(),
            )
        )
        return 0
    except AudiaGenticError as exc:
        if "request" in locals() and "evidence" in locals():
            _write(_safe_error(request, evidence, exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - raw worker failures never cross the pipe
        _emit_worker_diagnostic(exc)
        if "request" in locals() and "evidence" in locals():
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
