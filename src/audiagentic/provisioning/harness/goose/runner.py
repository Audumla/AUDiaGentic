from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def resolve_goose_bin(root: Path) -> Path:
    env_bin = os.environ.get("GOOSE_BIN")
    if env_bin:
        path = Path(env_bin)
        if path.exists():
            return path
    candidate = root / ".audiagentic" / "provisioning" / "goose" / "bin" / ("goose.exe" if os.name == "nt" else "goose")
    if candidate.exists():
        return candidate
    raise SystemExit("Goose binary not found.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AUDiaGentic Goose harness.")
    parser.add_argument("workdir", nargs="?", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    goose_bin = resolve_goose_bin(root)
    workdir = Path(args.workdir) if args.workdir else root
    runtime_dir = root / ".audiagentic" / "runtime" / "goose"
    log_dir = root / ".audiagentic" / "provisioning" / "logs" / "goose"
    log_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("sessions", "logs", "config", "state", "data"):
        (runtime_dir / sub).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("OPENAI_HOST", "http://127.0.0.1:42001")
    env.setdefault("OPENAI_API_KEY", "dummy")
    env.setdefault("GOOSE_PROVIDER", "openai")
    env.setdefault("GOOSE_MODEL", "Qwen_Qwen3.5-2B-Q4_K_S.gguf")
    env.setdefault("GOOSE_MODE", "chat")
    env.setdefault("GOOSE_MAX_TURNS", "20")
    env.setdefault("GOOSE_TEMPERATURE", "0.1")
    env.setdefault("GOOSE_TELEMETRY_ENABLED", "false")
    env.setdefault("GOOSE_PATH_ROOT", str(runtime_dir))

    log_path = log_dir / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    print("Launching Goose:")
    print(f"  OPENAI_HOST={env['OPENAI_HOST']}")
    print(f"  GOOSE_MODEL={env['GOOSE_MODEL']}")
    print(f"  WORKDIR={workdir}")
    print(f"  LOG={log_path}")

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": "goose_run_started",
                    "workdir": str(workdir),
                    "openai_host": env["OPENAI_HOST"],
                    "goose_model": env["GOOSE_MODEL"],
                },
                indent=2,
            )
            + "\n"
        )

    completed = subprocess.run([str(goose_bin), "session"], cwd=workdir, env=env, check=False)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "goose_run_finished", "returncode": int(completed.returncode)}) + "\n")
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
