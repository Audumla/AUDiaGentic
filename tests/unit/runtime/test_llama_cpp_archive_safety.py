from __future__ import annotations

import tarfile
from io import BytesIO

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.rig.embedded.binaries import _extract_tar_gz


def _archive(path, *, link_target: str) -> None:
    with tarfile.open(path, "w:gz") as archive:
        binary = tarfile.TarInfo("payload/llama-server")
        binary.size = 1
        archive.addfile(binary, BytesIO(b"x"))
        link = tarfile.TarInfo("payload/llama-cli")
        link.type = tarfile.SYMTYPE
        link.linkname = link_target
        archive.addfile(link)


def test_tar_extraction_allows_contained_relative_links(tmp_path) -> None:
    archive = tmp_path / "safe.tar.gz"
    _archive(archive, link_target="llama-server")

    _extract_tar_gz(archive, tmp_path / "out", "llama-server")

    assert (tmp_path / "out" / "llama-server").is_file()


@pytest.mark.parametrize("link_target", ["/etc/passwd", "../../escape"])
def test_tar_extraction_rejects_escaping_links(tmp_path, link_target: str) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    _archive(archive, link_target=link_target)

    with pytest.raises(AudiaGenticError, match="unsafe link"):
        _extract_tar_gz(archive, tmp_path / "out", "llama-server")
