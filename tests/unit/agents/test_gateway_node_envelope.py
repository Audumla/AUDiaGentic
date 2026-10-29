"""Root-independent checks preserve ordinary envelope validation and error ordering."""

from dataclasses import replace

import pytest

from audiagentic.components.agents.contracts import execution_context as contracts
from audiagentic.components.agents.contracts.execution_context import (
    SessionSpec,
    SubmissionEnvelope,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def envelope(**changes):
    return replace(SubmissionEnvelope(project_root="unused", prompt_body="Read"), **changes)


@pytest.mark.parametrize("root", [None, "", "relative/path", "C:\\foreign\\root", object()])
def test_validate_fields_does_not_inspect_root_or_canonicalize(root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("field validation resolved a root")

    monkeypatch.setattr(contracts, "canonicalize_project_root", forbidden)
    value = envelope(project_root=root)
    assert value.validate_fields() is None
    assert value.project_root is root


@pytest.mark.parametrize(
    "changes,code,field",
    [
        ({"schema_version": True}, "VAL-AGW-082", "schema_version"),
        ({"idempotency_key": 1}, "VAL-AGW-082", "idempotency_key"),
        ({"correlation_id": ""}, "VAL-AGW-082", "correlation_id"),
        ({"source": 7}, "VAL-AGW-082", "source"),
        ({"execution_profile_id": ""}, "VAL-AGW-082", "execution_profile_id"),
        ({"provider_id": False}, "VAL-AGW-082", "provider_id"),
        ({"model_id": 1}, "VAL-AGW-082", "model_id"),
        ({"component_profile": 1}, "VAL-AGW-082", "component_profile"),
        ({"mode": None}, "VAL-AGW-082", "mode"),
        ({"timeout_seconds": float("nan")}, "VAL-AGW-082", "timeout_seconds"),
        ({"session": {}}, "VAL-AGW-082", "session"),
        ({"session": SessionSpec(keep_alive=1)}, "VAL-AGW-082", "session.keep_alive"),
        ({"prompt_body": None}, "VAL-AGW-082", "prompt_body"),
        ({"metadata": {"value": object()}}, "VAL-AGW-082", "metadata"),
        ({"schema_version": 999}, "VAL-AGW-069", None),
        ({"provider_id": "codex"}, "VAL-AGW-063", None),
        ({"mode": "other"}, "VAL-AGW-066", None),
        ({"metadata": {"key": "Bearer " + "a" * 48}}, "VAL-AGW-065", None),
    ],
)
def test_fields_and_ordinary_validation_have_identical_errors(tmp_path, changes, code, field):
    value = envelope(project_root=str(tmp_path), **changes)
    errors = []
    for operation in (value.validate_fields, value.validate):
        with pytest.raises(AudiaGenticError) as caught:
            operation()
        errors.append(caught.value)
    assert errors[0].code == errors[1].code == code
    assert errors[0].message == errors[1].message
    assert errors[0].details == errors[1].details
    if field is not None:
        assert errors[0].details["field"] == field


def test_ordinary_root_string_check_still_runs_first(monkeypatch):
    def forbidden(self):
        raise AssertionError("non-root checks preceded root string validation")

    monkeypatch.setattr(SubmissionEnvelope, "validate_fields", forbidden)
    with pytest.raises(AudiaGenticError) as caught:
        envelope(project_root="", schema_version=False).validate()
    assert caught.value.code == "VAL-AGW-082"
    assert caught.value.details == {"field": "project_root"}


def test_ordinary_canonicalization_runs_after_fields_and_receives_actual_root(
    tmp_path, monkeypatch
):
    original = SubmissionEnvelope.validate_fields
    events = []
    root = str(tmp_path)
    canonical = contracts.CanonicalRoot(display=root, fingerprint=root)

    def fields(self):
        events.append("fields")
        original(self)

    def canonicalize(actual_root, *, windows):
        assert actual_root == root and windows is False
        events.append("canonicalize")
        return canonical

    monkeypatch.setattr(SubmissionEnvelope, "validate_fields", fields)
    monkeypatch.setattr(contracts, "canonicalize_project_root", canonicalize)
    assert envelope(project_root=root).validate(windows=False) is canonical
    assert events == ["fields", "canonicalize"]


@pytest.mark.parametrize(
    "changes,code,field",
    [
        ({"schema_version": 999, "prompt_body": None}, "VAL-AGW-082", "prompt_body"),
        ({"provider_id": "codex", "mode": "other"}, "VAL-AGW-063", None),
        ({"mode": "other", "metadata": {"key": "Bearer " + "a" * 48}}, "VAL-AGW-066", None),
    ],
)
def test_existing_nonroot_error_precedence_before_path_resolution(changes, code, field):
    with pytest.raises(AudiaGenticError) as caught:
        envelope(project_root="relative/root", **changes).validate()
    assert caught.value.code == code
    if field is not None:
        assert caught.value.details["field"] == field


def test_valid_fields_do_not_relax_ordinary_relative_root_rejection():
    value = envelope(project_root="relative/root")
    value.validate_fields()
    with pytest.raises(AudiaGenticError) as caught:
        value.validate()
    assert caught.value.code == "VAL-AGW-062"


def test_extraction_does_not_strengthen_existing_raw_fields():
    value = envelope(
        component_profile="",
        prompt_body=" ",
        work_id=17,
        context_id=False,
        message_id=[],
        agent_config_fingerprint="unvalidated",
        eligible_instance_ids=(1,),
    )
    before = value.to_mapping()
    assert value.validate_fields() is None
    assert value.to_mapping() == before
