"""Shared SHA-256 helpers: one definition of a lowercase digest and of canonical JSON."""
import hashlib
import math

import pytest

from audiagentic.foundation.digest import canonical_digest, canonical_json_bytes, is_sha256_hex, sha256_hex

GOOD = "a" * 64


@pytest.mark.parametrize("value", [GOOD, "0123456789abcdef" * 4, hashlib.sha256(b"x").hexdigest()])
def test_accepts_lowercase_hex_digest(value):
    assert is_sha256_hex(value)


@pytest.mark.parametrize(
    "value", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, " " + "a" * 63, "a" * 63 + "\n", b"a" * 64, None, 7, ["a"] * 64]
)
def test_rejects_everything_else(value):
    assert not is_sha256_hex(value)  # includes a trailing newline, which re.match would let through


def test_canonical_json_is_order_insensitive_compact_and_utf8():
    assert canonical_json_bytes({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == b'{"a":[1,{"c":3,"d":2}],"b":1}'
    assert canonical_json_bytes({"k": "é"}) == '{"k":"é"}'.encode()


@pytest.mark.parametrize("value", [math.nan, math.inf, {"k": {1, 2}}, {"k": b"x"}])
def test_canonical_json_rejects_unrepresentable_values(value):
    with pytest.raises((ValueError, TypeError)):
        canonical_json_bytes(value)


def test_digests():
    assert sha256_hex("abc") == sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()
    assert canonical_digest({"b": 1, "a": 2}) == canonical_digest({"a": 2, "b": 1}) == sha256_hex(b'{"a":2,"b":1}')
