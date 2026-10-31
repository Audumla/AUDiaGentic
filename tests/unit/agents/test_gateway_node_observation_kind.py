"""Node milestones share observation custody without masquerading as DOM polls."""
import hashlib
import json

import pytest

from audiagentic.components.agents.agents_paths import (
    gateway_observation_index_path,
    gateway_observation_path,
)
from audiagentic.components.agents.gateway import observability as obs
from audiagentic.foundation.io import iter_ndjson
from audiagentic.foundation.observability.journal_segments import has_segments


def test_event_families_never_coalesce_but_dom_default_still_does(tmp_path):
    facts = {"stage": "prepared"}
    kinds = ["dom-observed", "node-stage-observed", "node-stage-observed", "dom-observed", "dom-observed"]
    events = [obs.append_observation(tmp_path, "req_families", event_kind=kind, poll_seq=i,
                                     diagnostic_facts=facts) for i, kind in enumerate(kinds, 1)]
    assert [e["event"] for e in events] == [
        "dom-observed", "node-stage-observed", "node-stage-observed", "dom-observed", "observation-coalesced",
    ]
    assert [e["event_seq"] for e in events] == [1, 2, 3, 4, 5]
    assert events[-1]["coalesced"]["first_event_seq"] == 4
    assert events[-1]["coalesced"]["repeat_count"] == 2
    assert all("coalesced" not in e for e in events[1:4])
    # The existing facts digest is unchanged; family separation is explicit,
    # not a new digest/hash authority or a hidden payload change.
    assert len({e["current_digest"] for e in events}) == 1
    assert all(events[i]["previous_digest"] == events[i - 1]["current_digest"] for i in range(1, len(events)))


def test_default_matches_explicit_dom_and_historical_digest(tmp_path):
    first = obs.append_observation(tmp_path, "req_dom", poll_seq=1, dom_signals={"stop-control": True})
    second = obs.append_observation(tmp_path, "req_dom", event_kind="dom-observed", poll_seq=2,
                                    dom_signals={"stop-control": True})
    golden_parts = {"dom-signals": {"stop-control": True}, "activity": {}, "controls": {},
                    "diagnostic-facts": {}, "response-identity": {}, "error-occurrence": {}, "decision": {}, "action": {}}
    expected = hashlib.sha256(json.dumps(golden_parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert first["event"] == "dom-observed" and first["current_digest"] == expected
    assert second["event"] == "observation-coalesced" and second["current_digest"] == expected
    assert second["schema_version"] == first["schema_version"] == "gateway-observation.v1"


def test_node_milestones_are_durable_even_with_identical_facts_and_poll_number(tmp_path):
    for _ in range(12):
        obs.append_observation(tmp_path, "req_finite", event_kind="node-stage-observed", poll_seq=0,
                               diagnostic_facts={"stage": "receipt-committed"})
    page = obs.read_observation_page(tmp_path, "req_finite", limit=100)
    assert page["count"] == 12
    assert [e["event_seq"] for e in page["items"]] == list(range(1, 13))
    assert all(e["event"] == "node-stage-observed" and "coalesced" not in e for e in page["items"])
    assert len(list(iter_ndjson(gateway_observation_index_path(tmp_path, "req_finite")))) == 12


def test_mixed_family_cursor_tail_and_summary_use_existing_index(tmp_path):
    kinds = ["dom-observed", "node-stage-observed", "dom-observed", "node-stage-observed"]
    for i, kind in enumerate(kinds):
        obs.append_observation(tmp_path, "req_cursor", event_kind=kind, diagnostic_facts={"stage": "prepared", "sequence": i})
    first = obs.read_observation_page(tmp_path, "req_cursor", limit=2)
    second = obs.read_observation_page(tmp_path, "req_cursor", cursor=first["next_cursor"], limit=2)
    assert [e["event"] for e in first["items"] + second["items"]] == kinds
    assert [e["event_seq"] for e in first["items"] + second["items"]] == [1, 2, 3, 4]
    assert not second["has_more"] and second["next_cursor"] is None
    assert [e["event_seq"] for e in obs.read_observation_page(tmp_path, "req_cursor", tail=2)["items"]] == [3, 4]
    summary = obs.observation_summary(tmp_path, "req_cursor")
    assert summary["count"] == 4 and summary["latest"]["event"] == "node-stage-observed"


def test_narrow_node_fields_survive_projection_without_authority_claims(tmp_path):
    fields = {"stage": "prepared", "node-stage": "effect-authorized", "connection-generation": 2,
              "grant-revision": 3, "gateway-owner-epoch": "owner-2", "command-epoch": "owner-1",
              "receipt-stage": "terminal", "receipt-sequence": 4, "artifact-kind": "worker-terminal-result",
              "artifact-sha256": "a" * 64, "ack-sequence": 4, "elapsed-ms": 12.5}
    obs.append_observation(tmp_path, "req_projection", event_kind="node-stage-observed", diagnostic_facts=fields)
    result = obs.read_observation_page(tmp_path, "req_projection")["items"][0]
    assert result["facts"]["diagnostic-facts"] == fields
    assert "authorized" not in result  # These are observations, not grant/receipt validation.


def test_sensitive_content_and_opaque_objects_remain_excluded(tmp_path):
    fields = {"stage": "prepared", "raw-prompt": "PRIVATE-PROMPT", "output": "PRIVATE-OUTPUT",
              "private-path": "/PRIVATE-PATH", "native-ref": "PRIVATE-NATIVE", "socket": object(),
              "exception": ValueError("PRIVATE-EXCEPTION"), "exception-message": "PRIVATE-MESSAGE",
              "token": "PRIVATE-TOKEN", "response-text": "PRIVATE-RESPONSE"}
    obs.append_observation(tmp_path, "req_redact", event_kind="node-stage-observed", diagnostic_facts=fields)
    result = obs.read_observation_page(tmp_path, "req_redact")["items"][0]
    assert result["facts"]["diagnostic-facts"] == {"stage": "prepared"}
    assert "PRIVATE" not in gateway_observation_path(tmp_path, "req_redact").read_text(encoding="utf-8")


def test_existing_projection_size_depth_and_list_bounds_remain(tmp_path):
    fields = {"stage": "stage " * 200, "node-stage": ["node stage " * 100] * 50,
              "facts": {"facts": {"facts": {"stage": "too-deep"}}}}
    fields.update({f"metric-{i}": i for i in range(50)})
    event = obs.append_observation(tmp_path, "req_bounds", event_kind="node-stage-observed", diagnostic_facts=fields)
    projected = event["facts"]["diagnostic-facts"]
    assert len(projected) <= 32 and len(projected["stage"]) == 256
    assert len(projected["node-stage"]) == 32 and all(len(value) == 256 for value in projected["node-stage"])
    assert "too-deep" not in json.dumps(projected)


@pytest.mark.parametrize("digest", ["PRIVATE-PATH", "a" * 63, "A" * 64, ["PRIVATE-PATH"], 1, True])
def test_new_artifact_hash_field_drops_non_digest_text(tmp_path, digest):
    event = obs.append_observation(tmp_path, "req_bad_hash", event_kind="node-stage-observed",
                                   diagnostic_facts={"artifact-sha256": digest})
    assert event["facts"]["diagnostic-facts"] == {}


@pytest.mark.parametrize("kind", ["observation-coalesced", "node-effect-authorized", "PRIVATE", None, True, []])
def test_unknown_event_kind_uses_existing_value_error_pattern_before_journal_io(tmp_path, kind):
    with pytest.raises(ValueError, match="unsupported observation event kind") as caught:
        obs.append_observation(tmp_path, "req_invalid", event_kind=kind)
    assert "PRIVATE" not in str(caught.value)
    assert not gateway_observation_path(tmp_path, "req_invalid").exists()
    assert not gateway_observation_index_path(tmp_path, "req_invalid").exists()


def test_node_events_rotate_through_same_retention_segment_and_sequence_path(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import retention

    monkeypatch.setattr(retention, "journal_max_bytes", lambda name: 2500)
    for seq in range(1, 17):
        obs.append_observation(tmp_path, "req_rotate", event_kind="node-stage-observed" if seq % 2 else "dom-observed",
                               diagnostic_facts={"stage": "observed", "sequence": seq})
    assert has_segments(gateway_observation_path(tmp_path, "req_rotate"))
    first = obs.read_observation_page(tmp_path, "req_rotate", limit=7)
    second = obs.read_observation_page(tmp_path, "req_rotate", cursor=first["next_cursor"], limit=20)
    assert [item["event_seq"] for item in first["items"] + second["items"]] == list(range(1, 17))
    assert obs.observation_summary(tmp_path, "req_rotate")["last_event_seq"] == 16
