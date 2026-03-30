from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.jobs.prompt_parser import parse_prompt_launch_request


def test_parse_prompt_launch_request_normalizes_plan_prompt() -> None:
    request = parse_prompt_launch_request(
        "@plan target=packet:PKT-JOB-008 provider=codex model=gpt-5.4-mini profile=standard\n"
        "Continue implementing the packet.\n",
        surface="vscode",
        provider_id="codex",
        session_id="sess_001",
        workflow_profile="standard",
        prompt_id="prm_20260330_0001",
    )
    assert request["tag"] == "plan"
    assert request["target"] == {"kind": "packet", "packet-id": "PKT-JOB-008"}
    assert request["source"]["provider-id"] == "codex"
    assert request["source"]["model-id"] == "gpt-5.4-mini"
    assert request["prompt-body"].strip() == "Continue implementing the packet."


def test_parse_prompt_launch_request_accepts_provider_shorthand() -> None:
    request = parse_prompt_launch_request(
        "@codex\nShip the requested change.\n",
        surface="cli",
        provider_id=None,
        session_id="sess_002",
        workflow_profile="standard",
        prompt_id="prm_20260330_0002",
    )
    assert request["tag"] == "implement"
    assert request["source"]["provider-id"] == "codex"
    assert request["target"] == {"kind": "adhoc", "adhoc-id": "adh_20260330_0002"}
    assert request["target-origin"] == "default"
    assert request["source"]["model-id"] is None


def test_parse_prompt_launch_request_accepts_short_tag_alias() -> None:
    request = parse_prompt_launch_request(
        "@i target=packet:PKT-JOB-008 provider=codex\n"
        "Carry out the requested implementation.\n",
        surface="cli",
        provider_id=None,
        session_id="sess_003",
        workflow_profile="standard",
        prompt_id="prm_20260330_0003",
    )
    assert request["tag"] == "implement"
    assert request["source"]["provider-id"] == "codex"
    assert request["target"] == {"kind": "packet", "packet-id": "PKT-JOB-008"}
    assert request["target-origin"] == "explicit"


def test_parse_prompt_launch_request_accepts_adhoc_baseline() -> None:
    request = parse_prompt_launch_request(
        "@adhoc\nReview the plan and identify gaps.\n",
        surface="cli",
        provider_id="codex",
        session_id="sess_002",
        workflow_profile="standard",
        prompt_id="prm_20260330_0002",
        allow_adhoc_target=False,
    )
    assert request["tag"] == "implement"
    assert request["target"]["kind"] == "adhoc"
    assert request["target-origin"] == "explicit"


def test_parse_prompt_launch_request_rejects_majority_pass_in_mvp() -> None:
    try:
        parse_prompt_launch_request(
            "@review target=artifact:art_job_0007_impl_plan review-count=2 aggregation=majority-pass\n"
            "Check the artifact.\n",
            surface="cli",
            provider_id="claude",
            session_id="sess_003",
            workflow_profile="standard",
            prompt_id="prm_20260330_0003",
        )
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected validation error")
