"""AS40 step 1: codec/frame/bounds tests for the AG-bound Pi RPC tap decoder.

Covers only the pure JSONL codec (JsonlTapDecoder) -- the strict, bounded
parsing applied to the AG-bound tap copy only, per AS40's codec_process_layer
spec. Socket/pipe transport, the tee shim process itself, and byte-transparency
proof against the pi-acp-bound passthrough copy are separate, not-yet-built
pieces (tracked on AS40, not covered here).
"""
from __future__ import annotations

import json

from audiagentic.components.providers.adapters.pi.rpc_tap import (
    JsonlTapDecodeError,
    JsonlTapDecoder,
    JsonlTapFrame,
)


def _line(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def test_single_frame_decodes() -> None:
    decoder = JsonlTapDecoder()
    results = decoder.feed(_line({"type": "response", "command": "get_state", "success": True}))
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapFrame)
    assert results[0].payload == {"type": "response", "command": "get_state", "success": True}


def test_multiple_frames_in_one_chunk() -> None:
    decoder = JsonlTapDecoder()
    chunk = _line({"type": "agent_start"}) + _line({"type": "turn_start"}) + _line({"type": "agent_end"})
    results = decoder.feed(chunk)
    assert [r.payload["type"] for r in results] == ["agent_start", "turn_start", "agent_end"]


def test_frame_split_across_feeds_is_reassembled() -> None:
    decoder = JsonlTapDecoder()
    whole = _line({"type": "message_update", "assistantMessageEvent": {"delta": "hi"}})
    split_at = len(whole) // 2
    first = decoder.feed(whole[:split_at])
    assert first == []
    second = decoder.feed(whole[split_at:])
    assert len(second) == 1
    assert second[0].payload["type"] == "message_update"


def test_cr_lf_line_ending_is_stripped() -> None:
    decoder = JsonlTapDecoder()
    raw = json.dumps({"type": "agent_settled"}).encode("utf-8") + b"\r\n"
    results = decoder.feed(raw)
    assert len(results) == 1
    assert results[0].payload == {"type": "agent_settled"}


def test_blank_lines_are_skipped_not_errors() -> None:
    decoder = JsonlTapDecoder()
    chunk = b"\n\n" + _line({"type": "agent_start"}) + b"   \n"
    results = decoder.feed(chunk)
    assert len(results) == 1
    assert results[0].payload["type"] == "agent_start"


def test_invalid_json_line_is_a_bounded_decode_error_not_a_raise() -> None:
    decoder = JsonlTapDecoder()
    results = decoder.feed(b"not json at all\n")
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapDecodeError)
    assert results[0].reason == "invalid-json"
    assert decoder.parse_error_count == 1
    assert not decoder.exhausted


def test_non_object_json_line_is_a_decode_error() -> None:
    decoder = JsonlTapDecoder()
    results = decoder.feed(b"[1, 2, 3]\n")
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapDecodeError)
    assert results[0].reason == "invalid-json"


def test_invalid_utf8_line_is_a_decode_error() -> None:
    decoder = JsonlTapDecoder()
    results = decoder.feed(b"\xff\xfe not valid utf-8\n")
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapDecodeError)
    assert results[0].reason == "invalid-utf8"


def test_oversized_terminated_line_is_a_bounded_decode_error() -> None:
    decoder = JsonlTapDecoder(max_frame_bytes=16)
    oversized = _line({"type": "x", "padding": "y" * 100})
    results = decoder.feed(oversized)
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapDecodeError)
    assert results[0].reason == "oversized-frame"


def test_oversized_unterminated_buffer_is_dropped_not_buffered_forever() -> None:
    decoder = JsonlTapDecoder(max_frame_bytes=16)
    # No newline yet -- decoder must not grow the buffer unboundedly waiting for one.
    results = decoder.feed(b"x" * 100)
    assert len(results) == 1
    assert isinstance(results[0], JsonlTapDecodeError)
    assert results[0].reason == "oversized-frame"


def test_parse_errors_are_bounded_then_decoder_goes_inert() -> None:
    decoder = JsonlTapDecoder(max_parse_errors=3)
    for _ in range(3):
        results = decoder.feed(b"bad\n")
        assert len(results) == 1
    assert decoder.exhausted
    assert decoder.parse_error_count == 3
    # Further feeds are silently dropped once exhausted -- a tap failure
    # degrades observation evidence, it never raises into the caller.
    more = decoder.feed(_line({"type": "agent_start"}))
    assert more == []


def test_good_frames_interleaved_with_bad_ones_each_resolve_independently() -> None:
    decoder = JsonlTapDecoder()
    chunk = _line({"type": "agent_start"}) + b"garbage\n" + _line({"type": "agent_end"})
    results = decoder.feed(chunk)
    assert len(results) == 3
    assert isinstance(results[0], JsonlTapFrame)
    assert isinstance(results[1], JsonlTapDecodeError)
    assert isinstance(results[2], JsonlTapFrame)
    assert decoder.parse_error_count == 1
    assert not decoder.exhausted


def test_empty_feed_returns_empty_list() -> None:
    decoder = JsonlTapDecoder()
    assert decoder.feed(b"") == []
