"""Release bootstrap command implementation."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json
from audiagentic.foundation.components.registry import get_descriptor


def cmd_release_bootstrap(args: argparse.Namespace, project_root: Path) -> int:
    if not get_descriptor("agent-ledger"):
        print_error("ledger component not available")
        return 1

    from audiagentic.components.ledger.ledger_bootstrap import bootstrap_ledger

    bootstrap_root = Path(args.project_root).resolve() if args.project_root else project_root
    result = bootstrap_ledger(bootstrap_root)
    print_json(result, sort_keys=True)
    return 0
