"""Main CLI entrypoint."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = REPO_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import lifecycle_stub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audiagentic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lifecycle_parser = subparsers.add_parser("lifecycle-stub")
    lifecycle_parser.add_argument("--mode", required=True, choices=["plan", "apply", "validate"])
    lifecycle_parser.add_argument("--project-root", required=True)

    args = parser.parse_args(argv)
    if args.command == "lifecycle-stub":
        return lifecycle_stub.run(["--mode", args.mode, "--project-root", args.project_root])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
