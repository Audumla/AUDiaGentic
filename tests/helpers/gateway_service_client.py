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
    endpoint, token_file, project_root = sys.argv[1:]
    client = StandaloneGatewayClient(endpoint, load_auth_token(Path(token_file)))
    try:
        print(json.dumps(client.gateway_overview(Path(project_root)), sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    main()
