"""Contract gates for dynamically loaded session-transport builders."""

from __future__ import annotations

import inspect

import pytest

from audiagentic.components.providers.services.execution import execution
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _assert_builder_contract(builder) -> None:
    parameter = inspect.signature(builder).parameters.get("project_name")
    assert parameter is not None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_all_gpt_auto_alias_builders_require_project_name():
    for provider_id in ("gpt-auto", "gpt-auto-t1", "gpt-auto-t2"):
        builder = execution.load_session_transport_builder(provider_id)
        assert builder is not None
        _assert_builder_contract(builder)


def test_gpt_auto_surfaces_allow_gateway_context_drift():
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.foundation.transports.session_surface import SessionIdentityOperation

    descriptors = all_descriptors()
    for provider_id in ("gpt-auto", "gpt-auto-t1", "gpt-auto-t2"):
        declaration = descriptors[provider_id].session_surfaces[0]
        assert declaration.identity_operations[SessionIdentityOperation.RESUME_BY_REF].value == "supported"
        assert declaration.mapping_facts.requires_same_project is True
        assert declaration.mapping_facts.requires_same_execution_context is False
        assert declaration.evidence.validated is True


@pytest.mark.parametrize(
    "builder",
    [
        lambda project_root, *, config, ag_session_id, binding_sink: None,
        lambda project_root, *, config, **kwargs: None,
        lambda project_root, *, config, project_name=None: None,
    ],
)
def test_invalid_session_transport_builder_fails_at_discovery(
    monkeypatch: pytest.MonkeyPatch, builder
):
    monkeypatch.setattr(
        execution,
        "_adapter_hook",
        lambda provider_id, submodule, fn_name: builder,
    )
    with pytest.raises(AudiaGenticError) as exc:
        execution.load_session_transport_builder("fake-provider")
    assert exc.value.code == "INT-EXEC-004"
    assert exc.value.details["required-parameter"] == "project_name"


def test_session_transport_builder_contract_rejects_uninspectable_callable(
    monkeypatch: pytest.MonkeyPatch,
):
    class Uninspectable:
        def __call__(self, *args, **kwargs):
            return None

        @property
        def __signature__(self):
            raise ValueError("no signature")

    monkeypatch.setattr(
        execution,
        "_adapter_hook",
        lambda provider_id, submodule, fn_name: Uninspectable(),
    )
    with pytest.raises(AudiaGenticError) as exc:
        execution.load_session_transport_builder("fake-provider")
    assert exc.value.code == "INT-EXEC-004"
