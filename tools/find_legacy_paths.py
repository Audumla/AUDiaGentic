from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
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
PATTERNS = {
    "audiagentic.cli": re.compile(r"\baudiagentic\.cli\b"),
    "audiagentic.lifecycle": re.compile(r"\baudiagentic\.lifecycle\b"),
    "audiagentic.release": re.compile(r"\baudiagentic\.release\b"),
    "audiagentic.jobs": re.compile(r"\baudiagentic\.jobs\b"),
    "audiagentic.providers": re.compile(r"\baudiagentic\.providers\b"),
    "audiagentic.server": re.compile(r"\baudiagentic\.server\b"),
    "audiagentic.overlay.discord": re.compile(r"\baudiagentic\.overlay\.discord\b"),
    "src/audiagentic/jobs": re.compile(r"src[\\/]+audiagentic[\\/]+jobs"),
    "src/audiagentic/providers": re.compile(r"src[\\/]+audiagentic[\\/]+providers"),
    "src/audiagentic/lifecycle": re.compile(r"src[\\/]+audiagentic[\\/]+lifecycle"),
    "src/audiagentic/release": re.compile(r"src[\\/]+audiagentic[\\/]+release"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find legacy import and path references.")
    parser.add_argument("--root", action="append", dest="roots", help="Optional scan root relative to repo.")
    return parser.parse_args()


def iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and ".audiagentic\\runtime\\" not in str(path) and ".audiagentic/runtime/" not in str(path)
    ]


def main() -> int:
    args = parse_args()
    roots = args.roots or DEFAULT_SCAN_ROOTS
    missing = []
    findings: list[str] = []
    for raw_root in roots:
        root = REPO_ROOT / raw_root
        if not root.exists():
            missing.append(str(root))
            continue
        for path in iter_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in PATTERNS.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{line}: {label}")
    if findings:
        print("Legacy path/import references:")
        for finding in findings:
            print(f"- {finding}")
    else:
        print("No legacy path/import references found in the requested scan roots.")
    if missing:
        print("Missing scan roots:", file=sys.stderr)
        for root in missing:
            print(f"- {root}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
