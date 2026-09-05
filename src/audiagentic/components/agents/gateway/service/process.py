"""Internal detached-process entry point for the self-managed gateway."""
from __future__ import annotations

import argparse
import os
import sys
import subprocess
from pathlib import Path

from audiagentic.components.agents.gateway.service.host import GatewayServiceHost


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
    try:
        host.serve_forever()
    finally:
        host.close()
    if host.lifecycle.restart_requested:
        # Retire the old owner and release HTTP/provider resources first.
        # A new interpreter loads changed code, retaining the exact launch args.
        _launch_replacement(sys.argv[1:] if argv is None else argv)
    return 0


def _launch_replacement(argv: list[str]) -> None:
    """Launch without a shell or console; never inherit the retired owner epoch."""
    env = os.environ.copy()
    env.pop("AUDIAGENTIC_SERVICE_OWNER_EPOCH", None)
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
