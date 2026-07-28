from __future__ import annotations

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
