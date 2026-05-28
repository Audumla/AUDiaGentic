"""Tests for dedup infrastructure: _utils, base_extractor, cli, build_extractor_stream_sinks."""
from __future__ import annotations

import pytest

from audiagentic.components.optional.providers.adapters.cli import require_executable
from audiagentic.components.optional.providers.protocols.streaming._utils import _utc_now
from audiagentic.components.optional.providers.protocols.streaming.base_extractor import (
    BaseEventExtractor,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ── _utils ──────────────────────────────────────────────────────────────────

def test_utc_now_format() -> None:
    ts = _utc_now()
    assert ts.endswith("Z")
    assert "T" in ts
    assert "+00:00" not in ts


def test_utc_now_has_microsecond_precision() -> None:
    ts = _utc_now()
    assert ts.endswith("Z")
    assert "T" in ts
    assert "+00:00" not in ts
    # always 6 fractional digits
    frac = ts.split(".")[1].rstrip("Z")
    assert len(frac) == 6


# ── BaseEventExtractor enforcement ──────────────────────────────────────────

def test_base_extractor_requires_extractor_name() -> None:
    with pytest.raises(AttributeError, match="extractor_name"):
        class BadExtractor(BaseEventExtractor):
            def write(self, line: str) -> None: ...


def test_base_extractor_accepts_valid_subclass() -> None:
    class GoodExtractor(BaseEventExtractor):
        extractor_name = "test-extractor"

        def write(self, line: str) -> None: ...

    assert GoodExtractor.extractor_name == "test-extractor"


def test_base_extractor_emit_uses_extractor_name(tmp_path) -> None:

    events = []

    class CaptureSink:
        def write_event(self, payload): events.append(payload)
        def flush(self): pass
        def close(self): pass

    class TestExtractor(BaseEventExtractor):
        extractor_name = "test-xyz"
        def write(self, line: str) -> None:
            self._emit_event("task-progress", line.strip())

    extractor = TestExtractor(event_sink=CaptureSink(), job_id="j1", provider_id="test")
    extractor.write("hello\n")

    assert len(events) == 1
    assert events[0]["details"]["extractor"] == "test-xyz"
    assert events[0]["event-kind"] == "task-progress"
    assert events[0]["message"] == "hello"
    assert events[0]["job-id"] == "j1"


def test_base_extractor_emit_with_raw_payload() -> None:
    events = []

    class CaptureSink:
        def write_event(self, payload): events.append(payload)
        def flush(self): pass
        def close(self): pass

    class TestExtractor(BaseEventExtractor):
        extractor_name = "test-raw"
        def write(self, line: str) -> None: ...

    extractor = TestExtractor(event_sink=CaptureSink(), job_id="j2", provider_id="p2")
    extractor._emit_event("tool-call", "msg", {"key": "val"})

    assert events[0]["details"]["raw"] == {"key": "val"}


def test_base_extractor_emit_without_raw_payload() -> None:
    events = []

    class CaptureSink:
        def write_event(self, payload): events.append(payload)
        def flush(self): pass
        def close(self): pass

    class TestExtractor(BaseEventExtractor):
        extractor_name = "test-noraw"
        def write(self, line: str) -> None: ...

    extractor = TestExtractor(event_sink=CaptureSink(), job_id="j3", provider_id="p3")
    extractor._emit_event("task-progress", "msg")

    assert "raw" not in events[0]["details"]


# ── require_executable ───────────────────────────────────────────────────────

def test_require_executable_finds_python(monkeypatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "python" else None)
    result = require_executable("test-provider", "python")
    assert result == "/usr/bin/python"


def test_require_executable_tries_aliases_in_order(monkeypatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}" if name == "pdx" else None)
    result = require_executable("plandex", "plandex", "pdx")
    assert result == "/bin/pdx"


def test_require_executable_raises_when_not_found(monkeypatch) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(AudiaGenticError) as exc_info:
        require_executable("myprovider", "myexe", "myexe2")
    err = exc_info.value
    assert err.details["provider-id"] == "myprovider"
    assert "myexe" in err.details["aliases"]
    assert "myexe2" in err.details["aliases"]


# ── build_extractor_stream_sinks ─────────────────────────────────────────────

def test_build_extractor_stream_sinks_no_event_sink() -> None:
    """When no working-root/job-id, no NormalizedEventSink exists; extractor not added."""
    from audiagentic.components.optional.providers.protocols.streaming.provider_streaming import (
        build_extractor_stream_sinks,
    )

    class TestExtractor(BaseEventExtractor):
        extractor_name = "test-e"
        def write(self, line: str) -> None: ...

    stdout_sinks, _ = build_extractor_stream_sinks(
        TestExtractor,
        packet_ctx={},
        stream_controls={"tee-console": False},
    )
    # No NormalizedEventSink was created (no working-root/job-id), so no extractor
    assert not any(isinstance(s, TestExtractor) for s in stdout_sinks)


def test_build_extractor_stream_sinks_with_event_sink(tmp_path) -> None:
    """With working-root+job-id, extractor replaces the NormalizedEventSink."""
    from audiagentic.components.optional.providers.protocols.streaming.provider_streaming import (
        build_extractor_stream_sinks,
    )
    from audiagentic.components.optional.providers.protocols.streaming.sinks import (
        NormalizedEventSink,
    )

    class TestExtractor(BaseEventExtractor):
        extractor_name = "test-e2"
        def write(self, line: str) -> None: ...

    packet_ctx = {
        "working-root": str(tmp_path),
        "job-id": "job-abc",
        "provider-id": "test",
    }
    stdout_sinks, _ = build_extractor_stream_sinks(
        TestExtractor,
        packet_ctx=packet_ctx,
        stream_controls={"tee-console": False},
    )
    # Extractor should be present, NormalizedEventSink should not be directly in list
    assert any(isinstance(s, TestExtractor) for s in stdout_sinks)
    assert not any(isinstance(s, NormalizedEventSink) for s in stdout_sinks)


# ── Adapter extractor_name values ────────────────────────────────────────────

@pytest.mark.parametrize("adapter_path,cls_name,expected_name", [
    ("audiagentic.components.optional.providers.adapters.claude.adapter", "ClaudeEventExtractor", "claude-stream-json"),
    ("audiagentic.components.optional.providers.adapters.cline.adapter", "ClineEventExtractor", "cline-ndjson"),
    ("audiagentic.components.optional.providers.adapters.codex.adapter", "CodexEventExtractor", "codex-milestone"),
    ("audiagentic.components.optional.providers.adapters.copilot.adapter", "CopilotEventExtractor", "copilot-plaintext"),
    ("audiagentic.components.optional.providers.adapters.gemini.adapter", "GeminiEventExtractor", "gemini-plaintext"),
    ("audiagentic.components.optional.providers.adapters.opencode.adapter", "OpencodeEventExtractor", "opencode-ndjson"),
    ("audiagentic.components.optional.providers.adapters.qwen.adapter", "QwenEventExtractor", "qwen-plaintext"),
])
def test_adapter_extractor_name(adapter_path, cls_name, expected_name) -> None:
    import importlib
    mod = importlib.import_module(adapter_path)
    cls = getattr(mod, cls_name)
    assert cls.extractor_name == expected_name
    assert issubclass(cls, BaseEventExtractor)
