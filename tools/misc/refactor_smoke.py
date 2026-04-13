"""Lightweight smoke checks for the v3 structural refactor.

Verifies that the key modules can be imported and that required paths exist.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

# Use the shared repo-root helper so this tool works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT

sys.path.insert(0, str(SRC_ROOT))

SMOKE_IMPORTS = [
    "audiagentic.channels.cli.main",
    "audiagentic.foundation.contracts.canonical_ids",
    "audiagentic.runtime.lifecycle.fresh_install",
    "audiagentic.release.bootstrap",
    "audiagentic.execution.jobs.prompt_launch",
    "audiagentic.foundation.config.provider_registry",
]
REQUIRED_PATHS = [
    "src/audiagentic/foundation/contracts/schemas",
    "docs/examples",
    ".audiagentic/project.yaml",
    ".audiagentic/providers.yaml",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight smoke checks for the refactor.")
    parser.add_argument(
        "--imports-only",
        action="store_true",
        help="Skip path checks and only run import smoke.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures: list[str] = []

    for module_name in SMOKE_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - smoke path
            failures.append(f"import failed for {module_name}: {exc}")

    if not args.imports_only:
        for raw_path in REQUIRED_PATHS:
            if not (REPO_ROOT / raw_path).exists():
                failures.append(f"missing required path: {raw_path}")

    if failures:
        print("Refactor smoke failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Refactor smoke passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
