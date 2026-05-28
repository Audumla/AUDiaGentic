from __future__ import annotations

import shutil
import subprocess


def _check_cmd(name: str, version_args: list[str]) -> tuple[bool, str]:
    path = shutil.which(name)
    if path is None:
        return False, f"{name}: missing"
    try:
        result = subprocess.run(
            [name, *version_args],
            check=True,
            capture_output=True,
            text=True,
        )
        output = (result.stdout or result.stderr).strip().splitlines()
        line = output[0] if output else "ok"
        return True, f"{name}: {line}"
    except Exception as exc:  # pragma: no cover - defensive smoke guard
        return False, f"{name}: present but not runnable ({exc})"


def main() -> int:
    checks = [
        ("python3", ["--version"]),
        ("pip", ["--version"]),
        ("pytest", ["--version"]),
        ("uv", ["--version"]),
        ("npm", ["--version"]),
    ]
    failures: list[str] = []

    print("Docker smoke checks:")
    for name, args in checks:
        ok, msg = _check_cmd(name, args)
        print(f"- {msg}")
        if not ok:
            failures.append(msg)

    if failures:
        print("Smoke failed:")
        for msg in failures:
            print(f"- {msg}")
        return 1

    print("Smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
