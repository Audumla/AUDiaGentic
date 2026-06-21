"""Provider-aware canonical ID validator CLI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audiagentic.cli_io import print_json
from audiagentic.foundation.contracts.validate_ids import scan_paths
from audiagentic.paths import REPO_ROOT


def _canonical_provider_ids() -> tuple[str, ...]:
    import audiagentic.components.optional.providers  # noqa: F401
    from audiagentic.components.optional.providers.descriptors.registry import (
        canonical_provider_ids,
    )

    return canonical_provider_ids()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate canonical component and provider ids.")
    parser.add_argument("paths", nargs="*", help="Paths to scan")
    args = parser.parse_args(argv)
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = [REPO_ROOT / "docs", REPO_ROOT / "docs" / "examples"]
    findings = scan_paths(paths, provider_ids=_canonical_provider_ids())
    status = "ok" if not findings else "error"
    payload = {"status": status, "findings": findings}
    print_json(payload, indent=2, sort_keys=True)
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
