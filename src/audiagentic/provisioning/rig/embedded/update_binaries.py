"""Update llama-server binaries to the latest ggml-org/llama.cpp release."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple


class PlatformRelease(NamedTuple):
    """Release asset info for a platform."""
    filename: str
    sha256: str
    is_zip: bool
    inner_exe: str  # executable name inside the archive


# Latest release as of 2026-05-18
RELEASE = "b9204"

RELEASES = {
    "win32": PlatformRelease(
        filename="llama-b9204-bin-win-cpu-x64.zip",
        sha256="762fdc1bb8aa4801ee1bd14aa1ef87b844567c30edeb323b11d3e63a902c199f",
        is_zip=True,
        inner_exe="llama-server.exe",
    ),
    "darwin": PlatformRelease(
        filename="llama-b9204-bin-macos-arm64.tar.gz",
        sha256="3182ca57962a18b21f459f74d51970456dc9e6b0255d6fa28c46dc272789b26d",
        is_zip=False,
        inner_exe="llama-server",
    ),
    "linux": PlatformRelease(
        filename="llama-b9204-bin-ubuntu-x64.tar.gz",
        sha256="fd98a89cf543daf15f9106809e1428aaf0a22a11fb4f2172edd14f445126c30e",
        is_zip=False,
        inner_exe="llama-server",
    ),
}


def _download(url: str, dest: Path) -> None:
    """Download a file with progress."""
    print(f"  Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  Saved to {dest}")


def _verify_sha256(path: Path, expected: str) -> None:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != expected:
        raise RuntimeError(f"SHA256 mismatch: got {h}, expected {expected}")
    print(f"  SHA256 verified")


def _extract_zip(zip_path: Path, dest_dir: Path, inner_exe: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    # llama windows zip contains a subdirectory; find the exe
    src = dest_dir / inner_exe
    if not src.exists():
        # Look inside the extracted subdirectory
        for p in dest_dir.iterdir():
            if p.is_dir():
                candidate = p / inner_exe
                if candidate.exists():
                    shutil.move(str(candidate), str(dest_dir / inner_exe))
                    shutil.rmtree(p)
                    return
        raise RuntimeError(f"Could not find {inner_exe} in extracted archive")


def _extract_tar_gz(tar_path: Path, dest_dir: Path, inner_exe: str) -> None:
    import tarfile
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest_dir)
    src = dest_dir / inner_exe
    if not src.exists():
        for p in dest_dir.iterdir():
            if p.is_dir():
                candidate = p / inner_exe
                if candidate.exists():
                    shutil.move(str(candidate), str(dest_dir / inner_exe))
                    shutil.rmtree(p)
                    return
        raise RuntimeError(f"Could not find {inner_exe} in extracted archive")


def _kill_running_server(target_dir: Path) -> None:
    """Kill any running llama-server that may have the binary locked."""
    import subprocess
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/IM", "llama-server.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        subprocess.run(["pkill", "-f", "llama-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def update_binaries(runtime_dir: Path | None = None) -> None:
    """Download and install llama-server binaries for the current platform."""
    import platform

    plat = sys.platform
    if plat not in RELEASES:
        print(f"Unsupported platform: {plat}", file=sys.stderr)
        sys.exit(1)

    release = RELEASES[plat]
    base_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{release.filename}"

    # Determine target directory
    if runtime_dir:
        target_dir = runtime_dir / "rig" / "bin" / "llama-server" / ("windows" if plat == "win32" else ("macOS" if plat == "darwin" else "linux"))
    else:
        # Default: current working directory's rig bin
        target_dir = Path.cwd() / "rig" / "bin" / "llama-server" / ("windows" if plat == "win32" else ("macOS" if plat == "darwin" else "linux"))

    target_dir.mkdir(parents=True, exist_ok=True)

    # Kill any running server that may lock the binary
    _kill_running_server(target_dir)

    # Download to temp
    tmp_dir = Path(__file__).parent / ".tmp_download"
    tmp_dir.mkdir(exist_ok=True)
    archive_path = tmp_dir / release.filename

    print(f"Updating llama-server to {RELEASE} for {plat}")
    _download(base_url, archive_path)
    _verify_sha256(archive_path, release.sha256)

    # Extract
    if release.is_zip:
        _extract_zip(archive_path, target_dir, release.inner_exe)
    else:
        _extract_tar_gz(archive_path, target_dir, release.inner_exe)

    bin_path = target_dir / release.inner_exe
    if not bin_path.exists():
        print(f"ERROR: {release.inner_exe} not found after extraction", file=sys.stderr)
        sys.exit(1)

    # Set executable permission on Unix
    if plat != "win32":
        bin_path.chmod(0o755)

    # Show version
    result = subprocess.run([str(bin_path), "--version"], capture_output=True, text=True)
    version_output = result.stdout.strip() or result.stderr.strip()
    print(f"Installed: {bin_path}")
    print(f"Version:   {version_output}")

    # Cleanup
    archive_path.unlink()
    tmp_dir.rmdir()
    print("Done.")


if __name__ == "__main__":
    update_binaries()
