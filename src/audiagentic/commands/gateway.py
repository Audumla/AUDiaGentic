"""Explicit standalone gateway service command."""
from __future__ import annotations

import argparse
from pathlib import Path


def cmd_gateway(args: argparse.Namespace, project_root: Path) -> int:
    del project_root
    if args.gateway_cmd != "serve":
        raise ValueError(f"unsupported gateway command: {args.gateway_cmd}")
    from audiagentic.components.agents.agents_gateway_service_host import GatewayServiceHost

    host = GatewayServiceHost.create(
        host=args.host,
        port=args.port,
        token_path=Path(args.token_file).resolve() if args.token_file else None,
    )
    print(f"gateway endpoint: {host.endpoint}")
    print(f"gateway token file: {host.token_path}")
    try:
        host.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        host.close()
    return 0


__all__ = ["cmd_gateway"]
