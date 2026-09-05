"""Small gateway-owned project avatars, independent of project configuration."""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import struct
import zlib
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_bytes

error = make_error_factory("VAL", "AGSV", "gateway-service")
MAX_IMAGE_BYTES = 128 * 1024


def project_image_id(project_root: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(project_root.resolve())).encode("utf-8")).hexdigest()


def image_path(service_root: Path, project_id: str) -> Path:
    if len(project_id) != 64 or any(c not in "0123456789abcdef" for c in project_id):
        raise error(23, "invalid dashboard project identity")
    return service_root / "dashboard-images" / (project_id + ".png")


def save_image(service_root: Path, project_id: str, encoded: str) -> None:
    """Accept only bounded PNG pixels; remove all ancillary metadata."""
    path = image_path(service_root, project_id)
    if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 4):
        raise error(23, "project image exceeds 128 KiB")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("not PNG")
        offset = 8
        chunks = []
        kinds = []
        pixels = []
        while offset < len(raw):
            length = struct.unpack_from(">I", raw, offset)[0]
            end = offset + length + 12
            if end > len(raw):
                raise ValueError("incomplete chunk")
            kind = raw[offset + 4:offset + 8]
            data = raw[offset + 8:end - 4]
            crc = struct.unpack_from(">I", raw, end - 4)[0]
            if zlib.crc32(kind + data) != crc:
                raise ValueError("invalid checksum")
            if not kinds:
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
                if kind != b"IHDR" or not (1 <= width <= 256 and 1 <= height <= 256) or (depth, color, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                    raise ValueError("expected small RGBA PNG")
            elif kind == b"IHDR":
                raise ValueError("duplicate header")
            if kind not in {b"IHDR", b"IDAT", b"IEND"}:
                if not kind[0] & 32:
                    raise ValueError("unsupported critical chunk")
            else:
                chunks.append(raw[offset:end])
            kinds.append(kind)
            if kind == b"IDAT":
                pixels.append(data)
            offset = end
            if kind == b"IEND":
                if length or offset != len(raw):
                    raise ValueError("invalid end")
                break
        if not kinds or kinds[-1] != b"IEND" or b"IDAT" not in kinds:
            raise ValueError("missing image data")
        expected = height * (1 + width * 4)
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(b"".join(pixels), expected + 1)
        if len(decoded) != expected or not decoder.eof or decoder.unused_data or any(decoded[y * (1 + width * 4)] > 4 for y in range(height)):
            raise ValueError("invalid pixel data")
    except (ValueError, struct.error, binascii.Error, IndexError, zlib.error) as exc:
        raise error(23, "project image must be a valid small RGBA PNG") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, b"\x89PNG\r\n\x1a\n" + b"".join(chunks))
