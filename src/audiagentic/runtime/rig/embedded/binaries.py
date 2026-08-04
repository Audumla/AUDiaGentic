"""Install the manifest-pinned llama.cpp release into a rig runtime."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
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


def _safe_members(names: list[str]) -> None:
    if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
        raise make_rig_binary_error("CON", 6, "Archive contains an unsafe member path.")


def _extract_zip(zip_path: Path, dest_dir: Path, inner_exe: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        _safe_members(zf.namelist())
        zf.extractall(dest_dir)
    _flatten_extracted_archive(dest_dir, inner_exe)


def _extract_tar_gz(tar_path: Path, dest_dir: Path, inner_exe: str) -> None:
    import tarfile
    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        _safe_members([member.name for member in members])
        for member in members:
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    raise make_rig_binary_error("CON", 6, "Archive contains an unsafe link target.")
        try:
            tf.extractall(dest_dir, members=members, filter="fully_trusted")
        except TypeError:
            # `filter` (PEP 706) is only backported to Python 3.11.4+/3.10.12+/
            # 3.9.17+/3.8.17+; older 3.11.x (e.g. Debian bookworm's system
            # python3, 3.11.2) raises TypeError on the kwarg. Extraction
            # without `filter` is exactly the "fully_trusted" behavior on
            # those interpreters (no filtering existed at all pre-3.12), so
            # this is not a security downgrade -- members were already
            # validated by `_safe_members` and the symlink check above.
            tf.extractall(dest_dir, members=members)
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


def installed_release(target_dir: Path) -> dict[str, str] | None:
    """Read recipe-owned release provenance without probing the network."""
    path = target_dir / ".audiagentic-llama-cpp.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    existing = installed_release(target_dir)
    if existing and existing.get("release-version") == release.tag and (target_dir / release.inner_exe).exists():
        print_message(f"llama.cpp {release.tag} is already verified at {target_dir}")
        return

    with tempfile.TemporaryDirectory(prefix="audiagentic-llama-cpp-") as temporary:
        tmp_dir = Path(temporary)
        archive_path = tmp_dir / release.filename
        stage_dir = target_dir.parent / f".{target_dir.name}.stage-{uuid.uuid4().hex}"
        _download(release.download_url, archive_path)
        _verify_sha256(archive_path, release.sha256)
        stage_dir.mkdir()
        try:
            if release.is_zip:
                _extract_zip(archive_path, stage_dir, release.inner_exe)
            else:
                _extract_tar_gz(archive_path, stage_dir, release.inner_exe)
            bin_path = stage_dir / release.inner_exe
            if not bin_path.exists():
                raise make_rig_binary_error("RES", 3, f"{release.inner_exe} not found after extraction", path=str(bin_path))
            if platform_key() != "win":
                bin_path.chmod(0o755)
            result = subprocess.run([*executable_command(bin_path), "--version"], capture_output=True, text=True)
            version_output = result.stdout.strip() or result.stderr.strip()
            if result.returncode != 0 or not version_output:
                raise make_rig_binary_error("CON", 7, "llama-server version probe failed", path=str(bin_path))
            (stage_dir / ".audiagentic-llama-cpp.json").write_text(json.dumps({
                "recipe-id": "llama-cpp", "release-version": release.tag,
                "asset-url": release.download_url, "sha256": release.sha256,
                "installed-version": version_output,
            }, indent=2) + "\n", encoding="utf-8")
            previous = target_dir.parent / f".{target_dir.name}.previous-{uuid.uuid4().hex}"
            if target_dir.exists():
                os.replace(target_dir, previous)
                # Windows cannot replace a non-empty directory atomically with
                # os.replace. The prior payload is already protected by the
                # rollback directory, so remove any directory entry left at
                # the destination before promoting the verified stage.
                if target_dir.exists():
                    shutil.rmtree(target_dir)
            try:
                os.replace(stage_dir, target_dir)
            except BaseException:
                if previous.exists():
                    os.replace(previous, target_dir)
                raise
            shutil.rmtree(previous, ignore_errors=True)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
    print_message(f"Installed: {target_dir / release.inner_exe}")
    print_message(f"Version:   {installed_release(target_dir).get('installed-version', release.tag)}")
    print_message("Done.")


if __name__ == "__main__":
    update_binaries()
