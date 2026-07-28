from __future__ import annotations

import pytest

import audiagentic.runtime.rig.embedded.release_manifest as release_manifest
from audiagentic.runtime.rig.embedded.release_manifest import (
    load_llama_cpp_release_asset,
)


def test_release_manifest_selects_pinned_asset_for_host() -> None:
    asset = load_llama_cpp_release_asset()

    assert asset.version == "b9204"
    assert asset.filename.startswith("llama-b9204-bin-")
    assert len(asset.sha256) == 64
    assert asset.download_url.endswith(f"/b9204/{asset.filename}")
    assert asset.archive in {"zip", "tar.gz"}


@pytest.mark.parametrize(
    ("host_platform", "architecture", "filename", "archive", "executable"),
    [
        ("win", "AMD64", "win-cpu-x64.zip", "zip", "llama-server.exe"),
        ("darwin", "arm64", "macos-arm64.tar.gz", "tar.gz", "llama-server"),
        ("linux", "x86_64", "ubuntu-x64.tar.gz", "tar.gz", "llama-server"),
    ],
)
def test_release_manifest_selects_each_supported_platform_asset(
    monkeypatch, host_platform, architecture, filename, archive, executable
) -> None:
    monkeypatch.setattr(release_manifest, "platform_key", lambda: host_platform)
    monkeypatch.setattr(release_manifest.platform, "machine", lambda: architecture)

    asset = load_llama_cpp_release_asset()

    assert asset.filename.endswith(filename)
    assert asset.archive == archive
    assert asset.executable == executable
