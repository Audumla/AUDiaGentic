"""Install the manifest-pinned llama.cpp release into a rig runtime."""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.system.process import executable_command
from audiagentic.runtime.rig.constants import platform_dir_name
from audiagentic.runtime.rig.embedded.release_manifest import load_llama_cpp_release_asset
from audiagentic.runtime.rig.errors import make_rig_binary_error
from audiagentic.runtime.system.platform import platform_key

logger = logging.getLogger(__name__)


class ReleaseInfo(NamedTuple):
    """Resolved release info for a platform."""
    tag: str
    filename: str
    sha256: str | None
    is_zip: bool
    inner_exe: str
    download_url: str


def _pinned_release() -> ReleaseInfo:
    asset = load_llama_cpp_release_asset()
    return ReleaseInfo(
        tag=asset.version,
        filename=asset.filename,
        sha256=asset.sha256,
        is_zip=asset.archive == "zip",
        inner_exe=asset.executable,
        download_url=asset.download_url,
    )


def _download(url: str, dest: Path) -> None:
    """Download a file with progress."""
    print_message(f"  Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print_message(f"  Saved to {dest}")


def _verify_sha256(path: Path, expected: str | None) -> None:
    if not expected:
        raise make_rig_binary_error("CFG", 1, "A pinned SHA256 is required for rig binary installation.")
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != expected:
        raise make_rig_binary_error(
            "CON",
            4,
            f"SHA256 mismatch: got {h}, expected {expected}",
            path=str(path),
            actual=h,
            expected=expected,
        )
    print_message("  SHA256 verified")


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
        raise make_rig_binary_error(
            "RES",
            5,
            f"Could not find {inner_exe} in extracted archive",
            dest_dir=str(dest_dir),
            inner_exe=inner_exe,
        )

    for child in extracted_root.iterdir():
        target = dest_dir / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))
    shutil.rmtree(extracted_root)


def update_binaries(runtime_dir: Path | None = None, target_bin_dir: Path | None = None) -> None:
    """Install the configured pinned llama.cpp release for the current platform."""

    release = _pinned_release()

    print_message(f"Found release {release.tag}, downloading {release.filename}")

    plat_dir = platform_dir_name()
    # Determine target directory
    if target_bin_dir:
        target_dir = target_bin_dir / "llama-server" / plat_dir
    elif runtime_dir:
        target_dir = runtime_dir / "bin" / "llama-server" / plat_dir
    else:
        from audiagentic.foundation.paths.home import global_harness_runtime

        # Package files are never an install target.  The default is the
        # recipe-owned global runtime; callers may explicitly select a project
        # runtime through target_bin_dir.
        target_dir = global_harness_runtime() / "rig" / "bin" / "llama-server" / plat_dir

    target_dir.mkdir(parents=True, exist_ok=True)

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
        raise make_rig_binary_error(
            "RES",
            3,
            f"{release.inner_exe} not found after extraction",
            path=str(bin_path),
        )

    # Set executable permission on Unix
    if platform_key() != "win":
        bin_path.chmod(0o755)

    # Show version
    result = subprocess.run([*executable_command(bin_path), "--version"], capture_output=True, text=True)
    version_output = result.stdout.strip() or result.stderr.strip()
    print_message(f"Installed: {bin_path}")
    print_message(f"Version:   {version_output}")

    # Cleanup
    archive_path.unlink()
    tmp_dir.rmdir()
    print_message("Done.")


if __name__ == "__main__":
    update_binaries()
