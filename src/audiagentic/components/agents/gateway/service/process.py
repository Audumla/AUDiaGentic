"""Internal detached-process entry point for the self-managed gateway."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

from audiagentic.components.agents.gateway.service.host import GatewayServiceHost

_CLOSE_DEADLINE_SECONDS = 30.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--service-root", type=Path, default=None)
    args = parser.parse_args(argv)
    # Provider adapters use this neutral URL contract when they create their
    # dedicated browser-window anchor. The gateway itself remains HTTP-only.
    os.environ["AUDIAGENTIC_GATEWAY_PORT"] = str(args.port)
    host = GatewayServiceHost.create(
        port=args.port,
        token_path=args.token_file,
        service_root=args.service_root,
    )
    host.lifecycle.restart_enabled = True
    unexpected_server_exit = False
    try:
        host.serve_forever()
    finally:
        # ``serve_forever`` should only return after an explicit lifecycle
        # action.  Treat an unannotated return as a failed service boundary:
        # otherwise the process can remain alive after its socket is closed
        # and the managed-service record falsely continues to say ``running``.
        unexpected_server_exit = not bool(
            getattr(host.lifecycle, "restart_requested", False)
            or getattr(host.lifecycle, "exit_reason", None)
        )
        if unexpected_server_exit:
            host.lifecycle.restart_requested = True
        if host.lifecycle.restart_requested:
            os.environ["AUDIAGENTIC_GATEWAY_RESTART_HANDOFF"] = "1"
        closed = _close_host_with_deadline(host)
    if not closed:
        _fence_stranded_host(host)
    if host.lifecycle.restart_requested or not closed:
        # Retire the old owner and release HTTP/provider resources first.
        # A new interpreter loads changed code, retaining the exact launch args.
        _launch_replacement(sys.argv[1:] if argv is None else argv)
        # Provider runtimes may leave non-daemon asyncio/thread resources alive
        # after host.close(). Do not let the retired owner remain attached to
        # CDP alongside its replacement; that creates duplicate observers and
        # competing tab activation/recovery work. The replacement is already
        # detached, so terminate this owner immediately.
        os._exit(0)
    return 0


def _close_host_with_deadline(host: GatewayServiceHost) -> bool:
    """Close the host without allowing provider teardown to strand the service."""
    finished = threading.Event()

    def close() -> None:
        try:
            host.close()
        finally:
            finished.set()

    threading.Thread(target=close, name="gateway-host-close", daemon=True).start()
    return finished.wait(_CLOSE_DEADLINE_SECONDS)


def _fence_stranded_host(host: GatewayServiceHost) -> None:
    """Release the managed owner before replacing a host stuck in teardown."""
    try:
        host.server.server_close()
    except Exception:
        pass
    try:
        host.owner.retire(expected_epoch=host.owner_epoch)
    except Exception:
        # The replacement's startup recovery remains the final authority; a
        # stale record must never keep this process alive indefinitely.
        pass


def _launch_replacement(argv: list[str]) -> None:
    """Launch without a shell or console; never inherit the retired owner epoch."""
    env = os.environ.copy()
    env.pop("AUDIAGENTIC_SERVICE_OWNER_EPOCH", None)
    # Handoff is a one-process shutdown instruction.  The replacement must
    # perform ordinary startup/teardown and must not suppress its own provider
    # cleanup if it is later stopped for a non-restart reason.
    env.pop("AUDIAGENTIC_GATEWAY_RESTART_HANDOFF", None)
    subprocess.Popen(
        [sys.executable, "-m", __package__ + ".process", *argv],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )


if __name__ == "__main__":
    raise SystemExit(main())
