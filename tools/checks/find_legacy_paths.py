"""Find legacy import and path references from before the v3 structural refactor.

Patterns reflect paths that were valid before the refactor and should now be
fully replaced. Any match here indicates an incomplete migration.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Use the shared repo-root helper so this tool works regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT

DEFAULT_SCAN_ROOTS = [
    "src",
    "tools",
    "tests",
    "docs",
    ".audiagentic",
    ".agents",
    ".claude",
    ".clinerules",
    ".github/workflows",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
]

# Pre-v3 import paths that should no longer appear in source.
PATTERNS: dict[str, re.Pattern[str]] = {
    # Top-level roots removed/moved
    "audiagentic.contracts (→ foundation.contracts)": re.compile(
        r"\baudiagentic\.contracts\b"
    ),
    "audiagentic.config (→ foundation.config)": re.compile(
        r"\baudiagentic\.config\b"
    ),
    "audiagentic.streaming (→ interoperability.protocols.streaming)": re.compile(
        r"\baudiagentic\.streaming\b"
    ),
    "audiagentic.execution.providers (→ interoperability.providers)": re.compile(
        r"\baudiagentic\.execution\.providers\b"
    ),
    "audiagentic.scoping (→ planning)": re.compile(
        r"\baudiagentic\.scoping\b"
    ),
    "audiagentic.runtime.release (→ release)": re.compile(
        r"\baudiagentic\.runtime\.release\b"
    ),
    "audiagentic.execution.jobs.store (→ runtime.state.jobs_store)": re.compile(
        r"\baudiagentic\.execution\.jobs\.store\b"
    ),
    "audiagentic.execution.jobs.session_input (→ runtime.state.session_input_store)": re.compile(
        r"\baudiagentic\.execution\.jobs\.session_input\b"
    ),
    # Old domain names in plain-text docs/scripts
    "src/audiagentic/contracts/ (→ foundation/contracts/)": re.compile(
        r"src[\\/]+audiagentic[\\/]+contracts[\\/]"
    ),
    "src/audiagentic/config/ (→ foundation/config/)": re.compile(
        r"src[\\/]+audiagentic[\\/]+config[\\/]"
    ),
    "src/audiagentic/streaming/ (→ interoperability/protocols/streaming/)": re.compile(
        r"src[\\/]+audiagentic[\\/]+streaming[\\/]"
    ),
    "src/audiagentic/execution/providers/ (→ interoperability/providers/)": re.compile(
        r"src[\\/]+audiagentic[\\/]+execution[\\/]+providers[\\/]"
    ),
    "src/audiagentic/runtime/release/ (→ release/)": re.compile(
        r"src[\\/]+audiagentic[\\/]+runtime[\\/]+release[\\/]"
    ),
    # Removed placeholder roots
    "audiagentic.core (removed)": re.compile(r"\baudiagentic\.core\b"),
    "audiagentic.observability (removed)": re.compile(r"\baudiagentic\.observability\b"),
    "audiagentic.nodes (removed)": re.compile(r"\baudiagentic\.nodes\b"),
    "audiagentic.discovery (removed)": re.compile(r"\baudiagentic\.discovery\b"),
    "audiagentic.federation (removed)": re.compile(r"\baudiagentic\.federation\b"),
    "audiagentic.connectors (removed)": re.compile(r"\baudiagentic\.connectors\b"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find legacy import and path references from pre-v3 refactor."
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Optional scan root relative to repo (may be repeated).",
    )
    return parser.parse_args()


def iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and ".audiagentic/runtime/" not in str(path).replace("\\", "/")
        and "__pycache__" not in str(path)
    ]


def main() -> int:
    args = parse_args()
    roots = args.roots or DEFAULT_SCAN_ROOTS
    missing: list[str] = []
    findings: list[str] = []

    for raw_root in roots:
        root = REPO_ROOT / raw_root
        if not root.exists():
            missing.append(raw_root)
            continue
        for path in iter_files(root):
            if path == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in PATTERNS.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{line}: {label}")

    if findings:
        print("Legacy path/import references found:")
        for finding in findings:
            print(f"- {finding}")
    else:
        print("No legacy path/import references found.")

    if missing:
        print("Skipped (not found):", file=sys.stderr)
        for root in missing:
            print(f"  {root}", file=sys.stderr)

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
