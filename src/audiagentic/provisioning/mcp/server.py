"""Stage 0 AUDiaGentic provisioning MCP smoke server."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised by missing optional dep only
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)


@dataclass(frozen=True)
class SmokeStatus:
    ok: bool
    readonly: bool
    smoke_only: bool
    repo_root: str | None
    python: str
    platform: str
    cwd: str


def get_smoke_status(readonly: bool, smoke_only: bool) -> SmokeStatus:
    """Return read-only harness status for Pi MCP connectivity checks."""
    return SmokeStatus(
        ok=True,
        readonly=readonly,
        smoke_only=smoke_only,
        repo_root=os.environ.get("AUDIAGENTIC_REPO_ROOT"),
        python=sys.version.split()[0],
        platform=platform.platform(),
        cwd=str(Path.cwd()),
    )


def build_server(readonly: bool = True, smoke_only: bool = True) -> FastMCP:
    mcp = FastMCP(
        "audiagentic-provisioning",
        instructions=(
            "AUDiaGentic provisioning Stage 0 smoke server. "
            "Read-only; exposes only audiagentic_smoke_status."
        ),
    )

    @mcp.tool(description="Return read-only Stage 0 provisioning smoke status.")
    def audiagentic_smoke_status() -> dict[str, Any]:
        return asdict(get_smoke_status(readonly=readonly, smoke_only=smoke_only))

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readonly", action="store_true", default=True)
    parser.add_argument("--smoke-only", action="store_true", default=True)
    parser.add_argument("--direct-smoke", action="store_true")
    args = parser.parse_args()

    if args.direct_smoke or os.environ.get("AUDIAGENTIC_MCP_DIRECT_SMOKE") == "1":
        print(json.dumps(asdict(get_smoke_status(args.readonly, args.smoke_only))))
        return 0

    build_server(readonly=args.readonly, smoke_only=args.smoke_only).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
