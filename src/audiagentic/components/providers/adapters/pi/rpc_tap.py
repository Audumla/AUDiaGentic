"""AS40: strict JSONL codec for the AG-bound Pi RPC tap stream.

Applies strict UTF-8, LF-delimited framing with a bounded frame size and a
bounded parse-error tolerance to the read-only AG-bound copy of the tapped
`pi --mode rpc` stdout. This codec is never applied to the pi-acp-bound
passthrough copy of the tee shim's fan-out — that copy must stay byte-for-byte
untouched (AS40 acceptance criteria: pi-acp's own ACP behavior is provably
unaffected by the tap's presence).

Framing matches the raw `pi --mode rpc` protocol documented in
docs/reference/PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/pi-status-probe.md
(LF-only delimiter, `\\r` stripped, `JSON.stringify(value) + "\\n"` on the Pi
side) and the pi-acp bridge's own stdout consumption confirmed in
pi-acp-bridge-probe.md (readline-based, tolerant of non-JSON prelude lines).

A malformed or oversized frame degrades observation evidence for that frame
only; the decoder never raises. This mirrors AS40's cleanup_and_recovery
contract: "a tap failure degrades observation evidence, never terminates or
corrupts the driven session."
"""
from __future__ import annotations

import json
from dataclasses import dataclass

DEFAULT_MAX_FRAME_BYTES = 1_048_576  # 1 MiB — generous bound for one RPC event/response
DEFAULT_MAX_PARSE_ERRORS = 50  # bounded tolerance before the tap goes inert


@dataclass(frozen=True)
class JsonlTapFrame:
    """One successfully decoded JSON object frame from the tapped stream."""

    payload: dict
    raw_length: int


@dataclass(frozen=True)
class JsonlTapDecodeError:
    """One bounded, non-fatal decode failure on the tapped stream."""

    reason: str  # "oversized-frame" | "invalid-utf8" | "invalid-json"
    raw_length: int


class JsonlTapDecoder:
    """Incremental LF-delimited JSONL decoder for the AG-bound tap copy only.

    Feed raw bytes as they arrive from the tap socket/pipe; get back decoded
    frames and bounded decode errors in stream order. Never raises.
    """

    def __init__(
        self,
        *,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        max_parse_errors: int = DEFAULT_MAX_PARSE_ERRORS,
    ) -> None:
        self._max_frame_bytes = max_frame_bytes
        self._max_parse_errors = max_parse_errors
        self._buffer = bytearray()
        self._parse_error_count = 0
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        """True once bounded parse-error tolerance is spent; decoder stays inert."""
        return self._exhausted

    @property
    def parse_error_count(self) -> int:
        return self._parse_error_count

    def feed(self, chunk: bytes) -> list[JsonlTapFrame | JsonlTapDecodeError]:
        """Feed raw bytes read from the tap; return decoded results in stream order."""
        if self._exhausted or not chunk:
            return []
        self._buffer.extend(chunk)
        results: list[JsonlTapFrame | JsonlTapDecodeError] = []
        while True:
            newline_idx = self._buffer.find(b"\n")
            if newline_idx < 0:
                if len(self._buffer) > self._max_frame_bytes:
                    results.append(JsonlTapDecodeError("oversized-frame", len(self._buffer)))
                    self._buffer.clear()
                    self._record_error()
                break
            raw = bytes(self._buffer[:newline_idx])
            del self._buffer[: newline_idx + 1]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            if not raw.strip():
                continue
            frame_or_error = self._decode_line(raw)
            results.append(frame_or_error)
            if isinstance(frame_or_error, JsonlTapDecodeError):
                self._record_error()
                if self._exhausted:
                    break
        return results

    def _decode_line(self, raw: bytes) -> JsonlTapFrame | JsonlTapDecodeError:
        if len(raw) > self._max_frame_bytes:
            return JsonlTapDecodeError("oversized-frame", len(raw))
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return JsonlTapDecodeError("invalid-utf8", len(raw))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return JsonlTapDecodeError("invalid-json", len(raw))
        if not isinstance(payload, dict):
            return JsonlTapDecodeError("invalid-json", len(raw))
        return JsonlTapFrame(payload=payload, raw_length=len(raw))

    def _record_error(self) -> None:
        self._parse_error_count += 1
        if self._parse_error_count >= self._max_parse_errors:
            self._exhausted = True
            self._buffer.clear()


__all__ = [
    "DEFAULT_MAX_FRAME_BYTES",
    "DEFAULT_MAX_PARSE_ERRORS",
    "JsonlTapDecodeError",
    "JsonlTapDecoder",
    "JsonlTapFrame",
]
