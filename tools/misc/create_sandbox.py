"""Create a destructive test sandbox."""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxPaths:
    root: Path
    repo: Path
    logs: Path
    artifacts: Path


def create_sandbox(temp_root: Path | None, test_id: str) -> SandboxPaths:
    if temp_root is None:
        base = Path(tempfile.mkdtemp(prefix="sandbox-"))
    else:
        base = temp_root / f"sandbox-{test_id}"
        base.mkdir(parents=True, exist_ok=True)

    repo = base / "repo"
    logs = base / "logs"
    artifacts = base / "artifacts"
    repo.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(parents=True, exist_ok=True)

    return SandboxPaths(root=base, repo=repo, logs=logs, artifacts=artifacts)


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create destructive test sandbox")
    parser.add_argument("test_id")
    parser.add_argument("--root", help="Optional root directory for sandbox")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else None
    sandbox = create_sandbox(root, args.test_id)
    print(json.dumps({k: str(v) for k, v in asdict(sandbox).items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
