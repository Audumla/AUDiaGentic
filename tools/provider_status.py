"""Report provider CLI and catalog status."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.contracts.errors import AudiaGenticError, to_error_envelope
from audiagentic.providers.status import build_provider_status


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Inspect provider CLI and catalog status.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--provider-id")
    args = parser.parse_args(argv)
    try:
        payload = build_provider_status(Path(args.project_root), provider_id=args.provider_id)
    except AudiaGenticError as exc:
        print(json.dumps(to_error_envelope(exc), indent=2, sort_keys=True))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
