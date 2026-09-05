import base64
import struct
import zlib

import pytest

from audiagentic.components.agents.gateway.service.dashboard_images import image_path, project_image_id, save_image
from audiagentic.foundation.contracts.errors import AudiaGenticError


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\xff")) + chunk(b"IEND", b"")


def test_image_survives_store_reopen_and_separates_same_named_projects(tmp_path):
    first = project_image_id(tmp_path / "one" / "project")
    second = project_image_id(tmp_path / "two" / "project")
    assert first != second
    save_image(tmp_path, first, base64.b64encode(png()).decode())
    assert image_path(tmp_path, first).read_bytes() == png()
    assert not image_path(tmp_path, second).exists()


@pytest.mark.parametrize("raw", [b"<svg onload='bad'/>", b"not png", png()[:-1], png()+b"extra", b"x"*140000], ids=["svg", "text", "incomplete", "trailing", "oversize"])
def test_invalid_image_cannot_overwrite_existing(tmp_path, raw):
    key = project_image_id(tmp_path)
    save_image(tmp_path, key, base64.b64encode(png()).decode())
    with pytest.raises(AudiaGenticError):
        save_image(tmp_path, key, base64.b64encode(raw).decode())
    assert image_path(tmp_path, key).read_bytes() == png()


def test_image_rejects_path_traversal(tmp_path):
    with pytest.raises(AudiaGenticError):
        save_image(tmp_path, "../elsewhere", base64.b64encode(png()).decode())
