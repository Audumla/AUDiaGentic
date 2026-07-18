"""Internal detached-process entry point for the self-managed gateway."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.components.agents.agents_gateway_service_host import GatewayServiceHost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args(argv)
    host = GatewayServiceHost.create(port=args.port, token_path=args.token_file)
    try:
        host.serve_forever()
    finally:
        host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
