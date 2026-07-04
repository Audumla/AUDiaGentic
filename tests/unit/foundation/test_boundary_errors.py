"""AR10: public boundaries raise AudiaGenticError with canonical codes."""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_probe_group_invalid_mode_raises_val_probe_001():
    from audiagentic.foundation.toolchains.probes import CompositeHealthCheck

    group = CompositeHealthCheck(checks=(), mode="nonsense")
    with pytest.raises(AudiaGenticError, match="VAL-PROBE-001"):
        group.check({})


def test_workflow_unknown_kind_raises_val_wkfl_001(tmp_path):
    from audiagentic.foundation.workflow.transitions import load_workflow

    wf = tmp_path / "workflows.yaml"
    wf.write_text("kinds: {}\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError, match="VAL-WKFL-001"):
        load_workflow(wf, "nope")


def test_workflow_unknown_workflow_raises_val_wkfl_002(tmp_path):
    from audiagentic.foundation.workflow.transitions import load_workflow

    wf = tmp_path / "workflows.yaml"
    wf.write_text("kinds:\n  item:\n    workflows: {}\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError, match="VAL-WKFL-002"):
        load_workflow(wf, "item")


def test_release_template_placeholder_raises_val_relp(monkeypatch):
    from audiagentic.components.release.release_please import manage

    monkeypatch.setitem(manage.TEMPLATE_PLACEHOLDERS, "baseline.yml", ["__SENTINEL__"])  # noqa: E501
    monkeypatch.setattr(manage.utils, "render", lambda name, subs: "text __SENTINEL__")
    with pytest.raises(AudiaGenticError, match="VAL-RELP-001"):
        manage._render_baseline()
