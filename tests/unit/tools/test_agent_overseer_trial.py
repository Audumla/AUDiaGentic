from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / ".audiagentic"
    / "research"
    / "agent-overseer"
    / "overseer_trial.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("overseer_trial", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_event_kind_maps_observed_opencode_variants() -> None:
    mod = _load_module()

    assert mod.normalize_event_kind("agent_thought_chunk") == "thought"
    assert mod.normalize_event_kind("tool_call_update") == "tool-call"
    assert mod.normalize_event_kind("usage_update") == "usage"
    assert mod.normalize_event_kind("available_commands_update") == "status"
    assert mod.normalize_event_kind("assistant-message") == "assistant-message"


def test_heartbeat_treats_raw_opencode_events_as_meaningful() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()
    original_meaningful = hb.last_meaningful_monotonic

    hb.on_event(SimpleNamespace(kind="tool_call_update", text=None, terminal=False, ext={}))

    assert hb.counts["tool_call_update"] == 1
    assert hb.last_meaningful_monotonic >= original_meaningful
    assert hb.snapshot()["event_samples"][-1]["normalized_kind"] == "tool-call"


def test_heartbeat_reconstructs_assistant_text_chunks() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()

    hb.on_event(SimpleNamespace(kind="assistant-message", text="TOKEN", terminal=False, ext={}))
    hb.on_event(SimpleNamespace(kind="assistant-message", text=": IBIS", terminal=False, ext={}))
    hb.on_event(SimpleNamespace(kind="assistant-message", text="-482", terminal=False, ext={}))

    snapshot = hb.snapshot()
    assert snapshot["assistant_text_joined"] == "TOKEN: IBIS-482"
    assert snapshot["last_text_excerpt"] == "-482"


def test_event_sample_preserves_raw_kind_and_error_excerpt() -> None:
    mod = _load_module()
    event = SimpleNamespace(
        sequence=7,
        kind="tool_call_update",
        text="running pytest",
        terminal=False,
        error={"code": "E", "message": "boom"},
        ext={"acp": {"raw_kind": "tool_call_update", "payload": {"large": "ignored"}}},
    )

    sample = mod.event_sample(event)

    assert sample["sequence"] == 7
    assert sample["kind"] == "tool_call_update"
    assert sample["normalized_kind"] == "tool-call"
    assert sample["raw_kind"] == "tool_call_update"
    assert sample["text"] == "running pytest"
    assert sample["error"]["code"] == "E"


def test_plan_preflight_accepts_active_concrete_plan() -> None:
    mod = _load_module()
    plan_file = mod.ROOT / "docs" / "planning" / "active" / "agent-sessions" / "AS11.md"

    result = mod.plan_preflight("AS11", plan_file)

    assert result["exists"] is True
    assert result["state"] == "pending"
    assert result["has_steps"] is True
    assert result["has_files"] is True
    assert result["has_validation"] is True


def test_plan_preflight_rejects_completed_plan_for_handoff() -> None:
    mod = _load_module()
    plan_file = mod.ROOT / "docs" / "planning" / "completed" / "managed-config-consistency" / "MA32.md"

    result = mod.plan_preflight("MA32", plan_file)

    assert result["exists"] is True
    assert result["ready_for_handoff"] is False
    assert "plan file is not under docs/planning/active" in result["problems"]


def test_append_jsonl_and_write_json_create_audit_artifacts(tmp_path: Path) -> None:
    mod = _load_module()
    jsonl = tmp_path / "run" / "control.jsonl"
    summary = tmp_path / "run" / "summary.json"

    mod.append_jsonl(jsonl, {"event": "open-start"})
    mod.write_json(summary, {"ok": True})

    assert '"event": "open-start"' in jsonl.read_text(encoding="utf-8")
    assert summary.read_text(encoding="utf-8").strip() == '{\n  "ok": true\n}'


def test_progress_baseline_stays_normal_for_mixed_progress() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()

    for i in range(20):
        hb.on_event(SimpleNamespace(kind="agent_thought_chunk", text=None, terminal=False, ext={}))
        hb.on_event(SimpleNamespace(kind="tool_call_update", text=f"pytest {i}", terminal=False, ext={}))
        hb.on_event(SimpleNamespace(kind="assistant-message", text=f"step {i}", terminal=False, ext={}))

    progress = hb.snapshot()["progress_baseline"]
    assert progress["classification"] == "normal"
    assert progress["events_since_progress"] == 0


def test_progress_baseline_flags_long_non_progress_run() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()
    hb.on_event(SimpleNamespace(kind="tool_call_update", text="started pytest", terminal=False, ext={}))

    for _ in range(320):
        hb.on_event(SimpleNamespace(kind="agent_thought_chunk", text=None, terminal=False, ext={}))

    progress = hb.snapshot()["progress_baseline"]
    assert progress["classification"] in {"suspicious", "likely-loop-or-wedge"}
    assert "many-events-without-progress" in progress["flags"]
    assert "long-same-kind-non-progress-run" in progress["flags"]


def test_progress_baseline_flags_repeated_text() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()

    for _ in range(10):
        hb.on_event(SimpleNamespace(kind="assistant-message", text="I need to inspect the files again.", terminal=False, ext={}))

    progress = hb.snapshot()["progress_baseline"]
    assert progress["classification"] in {"suspicious", "likely-loop-or-wedge"}
    assert "repeated-identical-text" in progress["flags"]


def test_progress_baseline_flags_event_cap_pressure_without_terminal() -> None:
    mod = _load_module()
    hb = mod.Heartbeat()
    hb.total_events = 9500
    hb.terminal_seen = False

    progress = mod.classify_progress(hb)

    assert progress["classification"] == "suspicious"
    assert "event-cap-pressure-without-terminal" in progress["flags"]
