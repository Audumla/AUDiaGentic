from __future__ import annotations

import argparse
import subprocess
import sys


SAFE_IMAGE_PATTERNS = (
    "audiagentic",
    "audia-provider-cli-test",
    "audiagentic-test",
    "audiagentic-release-test",
    "audiagentic-lifecycle-tests",
    "audiagentic-provider-cli-tests",
    "python:3.12-slim",
)

DEFAULT_KEEP_IMAGES = {
    "audiagentic:test-local",
    "python:3.12-slim",
    "node:22-slim",
}


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _print_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)


def cleanup_containers() -> None:
    result = _run(["docker", "ps", "-a", "--format", "{{.ID}} {{.Image}}"])
    if result.returncode != 0:
        _print_result(result)
        return

    ids: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        container_id, image = parts
        if any(pattern in image for pattern in SAFE_IMAGE_PATTERNS):
            ids.append(container_id)

    if not ids:
        print("No matching test containers to remove.")
        return

    rm = _run(["docker", "rm", "-f", *ids])
    _print_result(rm)


def cleanup_images(keep: set[str]) -> None:
    result = _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    if result.returncode != 0:
        _print_result(result)
        return

    images: list[str] = []
    for ref in result.stdout.splitlines():
        ref = ref.strip()
        if not ref or ref in keep:
            continue
        if any(pattern in ref for pattern in SAFE_IMAGE_PATTERNS):
            images.append(ref)

    if not images:
        print("No matching test images to remove.")
        return

    rmi = _run(["docker", "rmi", *images])
    _print_result(rmi)


def cleanup_build_cache(max_used_space: str) -> None:
    result = _run(["docker", "buildx", "prune", "-f", "--max-used-space", max_used_space])
    _print_result(result)


def show_df() -> None:
    result = _run(["docker", "system", "df"])
    _print_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean AUDiaGentic Docker test clutter.")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-cache", action="store_true")
    parser.add_argument("--max-used-space", default="1gb")
    parser.add_argument("--keep-image", action="append", default=[])
    args = parser.parse_args(argv)

    keep = set(DEFAULT_KEEP_IMAGES)
    keep.update(args.keep_image)

    cleanup_containers()
    if not args.skip_images:
        cleanup_images(keep)
    if not args.skip_cache:
        cleanup_build_cache(args.max_used_space)
    show_df()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
