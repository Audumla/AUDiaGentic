"""Seed an example AUDiaGentic project scaffold."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_ROOT = REPO_ROOT / "docs" / "examples" / "project-scaffold"


def seed_example_project(target: Path, overwrite: bool = False) -> None:
    if target.exists():
        if any(target.iterdir()) and not overwrite:
            raise FileExistsError(f"target not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    docs_root = target / "docs"
    for subdir in ("specifications", "implementation", "releases", "decisions"):
        (docs_root / subdir).mkdir(parents=True, exist_ok=True)

    audi_root = target / ".audiagentic"
    audi_root.mkdir(parents=True, exist_ok=True)
    (audi_root / "runtime").mkdir(parents=True, exist_ok=True)

    for name in ("project", "components", "providers"):
        source = SCAFFOLD_ROOT / ".audiagentic" / f"{name}.yaml.example"
        destination = audi_root / f"{name}.yaml"
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Seed an example AUDiaGentic project scaffold.")
    parser.add_argument("target", help="Target directory for the scaffold")
    parser.add_argument("--overwrite", action="store_true", help="Allow writing into non-empty target")
    args = parser.parse_args(argv)
    try:
        seed_example_project(Path(args.target), overwrite=args.overwrite)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2
    print(json.dumps({"status": "ok", "target": str(Path(args.target))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
