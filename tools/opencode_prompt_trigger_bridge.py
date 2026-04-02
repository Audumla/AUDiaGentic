#!/usr/bin/env python
"""opencode prompt-trigger bridge.

Scaffolded wrapper entrypoint that forwards tagged prompts into the shared
AUDiaGentic launch bridge.
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--surface", default="cli")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    sys.stdout.write(f"opencode bridge scaffold: {root} surface={args.surface}
")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
