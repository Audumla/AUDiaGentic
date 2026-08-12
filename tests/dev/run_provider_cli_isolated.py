from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.integration.providers.harness import provider_ids  # noqa: E402


def _mount_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":")
    suffix = resolved.as_posix().split(":", 1)[-1]
    if drive:
        return f"/{drive}{suffix}"
    return resolved.as_posix()


def _run_for_provider(provider_id: str, *, image: str, mount: str | None) -> tuple[bool, str]:
    create_cmd = [
        "docker",
        "create",
        "-e",
        "PYTHONPATH=/app/src",
        "-e",
        "AUDIAGENTIC_DOCKER_TESTS=1",
        "-e",
        "AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1",
        "-e",
        "WSL_DISTRO_NAME=",
        "-e",
        "WSL_INTEROP=",
        "-e",
        "WSLENV=",
        "-e",
        f"AUDIAGENTIC_PROVIDER_UNDER_TEST={provider_id}",
    ]
    if mount is not None:
        create_cmd.extend(["-v", f"{mount}:/app"])
    create_cmd.extend([
        image,
        "sh",
        "-lc",
        (
            "unset WSL_DISTRO_NAME WSL_INTEROP WSLENV && "
            "export PATH=/venv/bin:$HOME/.local/bin:/root/.local/bin:/usr/local/bin:$PATH && "
            "pytest "
            "tests/integration/providers/test_provider_cli_comprehensive.py "
            "tests/integration/providers/test_provider_cli_workflow_docker.py "
            "-q"
        ),
    ])
    cid = subprocess.check_output(create_cmd, text=True).strip()
    completed = subprocess.run(["docker", "start", "-a", cid], check=False)
    subprocess.run(["docker", "rm", "-f", cid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return completed.returncode == 0, provider_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real provider CLI Docker tests in isolated containers.")
    parser.add_argument("--image", default="audiagentic-test:latest")
    parser.add_argument("--provider", action="append", dest="providers", default=[])
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry a failed provider this many extra times in a fresh container.",
    )
    parser.add_argument(
        "--bind-mount",
        action="store_true",
        help="Bind-mount repo into container for faster iteration; less deterministic than copy-based mode.",
    )
    args = parser.parse_args()

    mount = _mount_path(ROOT) if args.bind_mount else None
    selected = args.providers or provider_ids()
    failures: list[str] = []

    for provider_id in selected:
        ok = False
        name = provider_id
        for attempt in range(args.retries + 1):
            ok, name = _run_for_provider(provider_id, image=args.image, mount=mount)
            if ok:
                break
            if attempt < args.retries:
                print(f"Retrying provider after failure: {provider_id} (attempt {attempt + 2}/{args.retries + 1})")
        if not ok:
            failures.append(name)

    if failures:
        print("Isolated provider CLI failures:")
        for provider_id in failures:
            print(f"- {provider_id}")
        return 1

    print("Isolated provider CLI runs passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
