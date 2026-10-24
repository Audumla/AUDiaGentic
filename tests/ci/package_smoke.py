"""Validate actual distribution bytes in a clean installation before publishing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def distribution_hashes(directory: Path) -> dict[str, str]:
    wheels = sorted(directory.glob("audiagentic-*.whl"))
    archives = sorted(directory.glob("audiagentic-*.tar.gz"))
    if len(wheels) != 1 or len(archives) != 1:
        raise ValueError("expected exactly one wheel and one source distribution")
    result = {}
    for path in [*wheels, *archives]:
        with path.open("rb") as stream:
            result[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--proof", type=Path, default=Path(".ci-results/artifact-provenance.json"))
    parser.add_argument("--source-sha", default=None)
    args = parser.parse_args()
    directory = args.dist.resolve()
    before = distribution_hashes(directory)
    expected = args.version.removeprefix("v")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"} and not key.startswith("AUDIAGENTIC_")
    }
    with tempfile.TemporaryDirectory(prefix="audia-wheel-proof-") as temporary:
        root = Path(temporary)
        installation = root / "venv"
        venv.EnvBuilder(with_pip=True).create(installation)
        python = installation / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        def run(*command: str) -> None:
            subprocess.run([str(python), *command], cwd=root, env=env, check=True, timeout=180)

        run(
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            str(next(directory.glob("*.whl"))),
        )
        run(
            "-I",
            "-c",
            "import importlib.metadata,pathlib,sys,audiagentic; "
            "assert importlib.metadata.version('audiagentic') == sys.argv[1]; "
            "assert pathlib.Path(audiagentic.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve()); "
            "from audiagentic.components.agents.gateway.service import process; "
            "assert callable(process.main); "
            "print('installed wheel import/version proof passed')",
            expected,
        )
        run("-I", "-m", "audiagentic.launcher", "--help")
    if distribution_hashes(directory) != before:
        raise ValueError("distribution bytes changed during validation")
    source = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if args.source_sha and source != args.source_sha:
        raise ValueError("artifact validation source differs from finalized release commit")
    args.proof.parent.mkdir(parents=True, exist_ok=True)
    args.proof.write_text(
        json.dumps({"version": expected, "source_sha": source, "sha256": before}, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
