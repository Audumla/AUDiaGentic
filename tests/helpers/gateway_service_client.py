"""Independent-process client probe for the standalone gateway integration gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from audiagentic.components.agents.gateway.remote_client import (
    StandaloneGatewayClient,
    load_auth_token,
)


def main() -> None:
    # Gateway payloads may contain provider text outside the Windows ANSI
    # code page. Always emit UTF-8 so a successful probe cannot fail while
    # printing its result after the gateway call has already completed.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    endpoint, token_file, project_root = sys.argv[1:]
    client = StandaloneGatewayClient(endpoint, load_auth_token(Path(token_file)))
    try:
        print(json.dumps(client.gateway_overview(Path(project_root)), sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    main()
