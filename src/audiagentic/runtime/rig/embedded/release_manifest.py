"""Pinned llama.cpp release declaration loader.

The manifest is config-owned and intentionally contains immutable asset URLs
derivable from a reviewed release tag plus required SHA-256 digests.  Runtime
code never asks GitHub which release happens to be latest.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.system.platform import platform_key


@dataclass(frozen=True)
class LlamaCppReleaseAsset:
    version: str
    filename: str
    sha256: str
    archive: str
    executable: str

    @property
    def download_url(self) -> str:
        return (
            "https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{self.version}/{self.filename}"
        )


def _manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "components" / "rig" / "llama-cpp-release.yaml"


def _asset_key() -> str:
    platform = platform_key()
    if platform == "win":
        return "win-x64"
    if platform == "darwin":
        return "darwin-arm64"
    if platform == "linux":
        return "linux-x64"
    return platform


def load_llama_cpp_release_asset() -> LlamaCppReleaseAsset:
    """Return the exact supported asset for this host or fail closed."""
    try:
        document = yaml.safe_load(_manifest_path().read_text(encoding="utf-8"))
        release = document["release"]
        asset = document["assets"][_asset_key()]
        version = str(release["version"])
        filename = str(asset["filename"])
        sha256 = str(asset["sha256"])
        archive = str(asset["archive"])
        executable = str(asset["executable"])
    except (KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        raise make_error(
            prefix="CFG", component="RIGBIN", number=1,
            kind="rig-binary", message="Invalid llama.cpp release manifest.",
            details={"path": str(_manifest_path()), "platform": _asset_key()},
        ) from exc
    if archive not in {"zip", "tar.gz"} or len(sha256) != 64:
        raise make_error(
            prefix="CFG", component="RIGBIN", number=1,
            kind="rig-binary", message="Invalid llama.cpp release asset declaration.",
            details={"platform": _asset_key(), "version": version},
        )
    return LlamaCppReleaseAsset(version, filename, sha256, archive, executable)


__all__ = ["LlamaCppReleaseAsset", "load_llama_cpp_release_asset"]
