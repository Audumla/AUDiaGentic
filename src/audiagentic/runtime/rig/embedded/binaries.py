"""Update llama-server binaries to the latest ggml-org/llama.cpp release."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

from audiagentic.foundation.system.process import executable_command

GITHUB_REPO = "ggml-org/llama.cpp"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"

# Filename patterns per platform: (display_name, regex_pattern, is_zip, inner_exe)
_PLATFORM_PATTERNS = {
    "win32": ("Windows", re.compile(r"^llama-[a-zA-Z0-9]+-bin-win-cpu-x64\.zip$", re.I), True, "llama-server.exe"),
    "darwin": ("macOS", re.compile(r"^llama-[a-zA-Z0-9]+-bin-macos-arm64\.tar\.gz$", re.I), False, "llama-server"),
    "linux": ("Linux", re.compile(r"^llama-[a-zA-Z0-9]+-bin-ubuntu-x64\.tar\.gz$", re.I), False, "llama-server"),
}


class ReleaseInfo(NamedTuple):
    """Resolved release info for a platform."""
    tag: str
    filename: str
    sha256: str | None
    is_zip: bool
    inner_exe: str
    download_url: str


def _http_get(url: str) -> bytes:
    """Perform an HTTP GET request."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _latest_release() -> dict:
    """Fetch the latest release from GitHub API."""
    print(f"Fetching latest release from {GITHUB_REPO} ...")
    data = _http_get(f"{GITHUB_API}/releases/latest")
    return json.loads(data)


def _find_asset_for_platform(release: dict, plat: str) -> ReleaseInfo | None:
    """Find the matching asset for the given platform in the release."""
    display, pattern, is_zip, inner_exe = _PLATFORM_PATTERNS[plat]
    tag = release.get("tag_name", release.get("name", "unknown"))

    # Try to find a SHA256 file alongside the asset
    assets = {a["name"]: a for a in release.get("assets", [])}

    for asset_name, asset in assets.items():
        if pattern.match(asset_name):
            # Look for a corresponding .sha256 file
            sha256 = None
            sha_name = f"{asset_name}.sha256"
            if sha_name in assets:
                try:
                    sha_content = _http_get(assets[sha_name]["browser_download_url"]).decode().strip()
                    sha_match = re.search(r"^[0-9a-fA-F]{64}", sha_content)
                    if sha_match:
                        sha256 = sha_match.group(0)
                except Exception:
                    logger.warning("Failed to read SHA256 for %s", sha_name)

            return ReleaseInfo(
                tag=tag,
                filename=asset_name,
                sha256=sha256,
                is_zip=is_zip,
                inner_exe=inner_exe,
                download_url=asset["browser_download_url"],
            )

    print(f"  No matching asset found for {display} in release {tag}", file=sys.stderr)
    print(f"  Expected pattern: {pattern.pattern}", file=sys.stderr)
    print("  Available assets:", file=sys.stderr)
    for a in release.get("assets", []):
        print(f"    - {a['name']}", file=sys.stderr)
    return None


def _download(url: str, dest: Path) -> None:
    """Download a file with progress."""
    print(f"  Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  Saved to {dest}")


def _verify_sha256(path: Path, expected: str | None) -> None:
    if not expected:
        print("  SHA256 not available, skipping verification")
        return
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != expected:
        raise RuntimeError(f"SHA256 mismatch: got {h}, expected {expected}")
    print("  SHA256 verified")


def _extract_zip(zip_path: Path, dest_dir: Path, inner_exe: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    _flatten_extracted_archive(dest_dir, inner_exe)


def _extract_tar_gz(tar_path: Path, dest_dir: Path, inner_exe: str) -> None:
    import tarfile
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest_dir)
    _flatten_extracted_archive(dest_dir, inner_exe)


def _flatten_extracted_archive(dest_dir: Path, inner_exe: str) -> None:
    """Flatten a single top-level extracted directory into dest_dir.

    New llama.cpp archives contain many companion DLL/impl files. We must move
    the full extracted payload, not only the executable, otherwise the runtime
    stays on stale old binaries.
    """
    extracted_root: Path | None = None
    for p in dest_dir.iterdir():
        if p.is_dir() and (p / inner_exe).exists():
            extracted_root = p
            break

    if extracted_root is None and (dest_dir / inner_exe).exists():
        return
    if extracted_root is None:
        raise RuntimeError(f"Could not find {inner_exe} in extracted archive")

    for child in extracted_root.iterdir():
        target = dest_dir / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))
    shutil.rmtree(extracted_root)


def _kill_running_server(target_dir: Path) -> None:
    """Kill any running llama-server that may have the binary locked."""
    import subprocess
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/IM", "llama-server.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            subprocess.run(["pkill", "-f", "llama-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except FileNotFoundError:
            pass  # pkill not available, server likely not running


def update_binaries(runtime_dir: Path | None = None, target_bin_dir: Path | None = None) -> None:
    """Download and install llama-server binaries for the current platform."""

    plat = sys.platform
    if plat not in _PLATFORM_PATTERNS:
        print(f"Unsupported platform: {plat}", file=sys.stderr)
        sys.exit(1)

    # Fetch latest release dynamically
    release_data = _latest_release()
    release = _find_asset_for_platform(release_data, plat)
    if not release:
        print(f"ERROR: Could not find matching asset for {plat}", file=sys.stderr)
        sys.exit(1)

    print(f"Found release {release.tag}, downloading {release.filename}")

    # Determine target directory
    if target_bin_dir:
        target_dir = target_bin_dir / "llama-server" / ("windows" if plat == "win32" else ("macOS" if plat == "darwin" else "linux"))
    elif runtime_dir:
        target_dir = runtime_dir / "bin" / "llama-server" / ("windows" if plat == "win32" else ("macOS" if plat == "darwin" else "linux"))
    else:
        # Default: bundled embedded rig bin next to this module.
        target_dir = Path(__file__).parent / "bin" / "llama-server" / ("windows" if plat == "win32" else ("macOS" if plat == "darwin" else "linux"))

    target_dir.mkdir(parents=True, exist_ok=True)

    # Kill any running server that may lock the binary
    _kill_running_server(target_dir)

    # Download to temp
    tmp_dir = Path(__file__).parent / ".tmp_download"
    tmp_dir.mkdir(exist_ok=True)
    archive_path = tmp_dir / release.filename

    _download(release.download_url, archive_path)
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
    result = subprocess.run([*executable_command(bin_path), "--version"], capture_output=True, text=True)
    version_output = result.stdout.strip() or result.stderr.strip()
    print(f"Installed: {bin_path}")
    print(f"Version:   {version_output}")

    # Cleanup
    archive_path.unlink()
    tmp_dir.rmdir()
    print("Done.")


if __name__ == "__main__":
    update_binaries()
