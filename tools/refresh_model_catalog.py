"""Write a provider model catalog to runtime storage."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.config.provider_catalog import write_model_catalog


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Refresh a provider model catalog.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--catalog-file", help="Path to a JSON catalog payload")
    args = parser.parse_args(argv)
    if args.catalog_file:
        payload = json.loads(Path(args.catalog_file).read_text(encoding="utf-8"))
    else:
        payload = json.loads(sys.stdin.read())
    path = write_model_catalog(Path(args.project_root), payload)
    print(json.dumps({"status": "ok", "path": str(path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
