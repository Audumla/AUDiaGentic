"""Unit tests for Compute Resource / Model Instance (AS105/AS101).

User-global config -- AUDIAGENTIC_HOME is already redirected to a per-test
tmp dir by tests/conftest.py's autouse `_isolate_audiagentic_home` fixture,
so no extra isolation setup is needed here.
"""
from __future__ import annotations

import pytest

from audiagentic.components.agents.models.compute_resource import (
    ComputeResource,
    ComputeResourceStore,
    compute_resource_from_dict,
    validate_compute_resource,
)
from audiagentic.components.agents.models.compute_resource_api import (
    create_compute_resource,
    delete_compute_resource,
    get_compute_resource,
    list_compute_resources,
    load_compute_resources,
    update_compute_resource,
)
from audiagentic.components.agents.models.model_instance import (
    ModelInstance,
    ModelInstanceStore,
    model_instance_from_dict,
    validate_model_instance,
)
from audiagentic.components.agents.models.model_instance_api import (
    create_model_instance,
    delete_model_instance,
    get_model_instance,
    list_instances_serving,
    list_model_instances,
    update_model_instance,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ── ComputeResource model ──────────────────────────────────────────────

def test_validate_compute_resource_minimal_valid():
    assert validate_compute_resource({"resource_id": "gpu-0", "kind": "local-gpu"}) == []


def test_validate_compute_resource_rejects_unknown_kind():
    issues = validate_compute_resource({"resource_id": "gpu-0", "kind": "quantum-computer"})
    assert any("kind must be one of" in i for i in issues)


def test_validate_compute_resource_accepts_all_declared_kinds():
    for kind in ("local-gpu", "remote-host", "hosted-api", "unbounded"):
        assert validate_compute_resource({"resource_id": "r", "kind": kind}) == []


def test_compute_resource_from_dict_invalid_raises():
    with pytest.raises(AudiaGenticError) as exc_info:
        compute_resource_from_dict({})
    assert exc_info.value.code == "VAL-CRES-001"


def test_compute_resource_store_duplicate_add_raises():
    store = ComputeResourceStore([ComputeResource(resource_id="r", kind="local-gpu")])
    with pytest.raises(AudiaGenticError) as exc_info:
        store.add(ComputeResource(resource_id="r", kind="remote-host"))
    assert exc_info.value.code == "RES-CRES-002"


def test_compute_resource_store_missing_get_raises():
    store = ComputeResourceStore()
    with pytest.raises(AudiaGenticError) as exc_info:
        store.get("nonexistent")
    assert exc_info.value.code == "RES-CRES-001"


# ── ModelInstance model ────────────────────────────────────────────────

def test_validate_model_instance_minimal_valid():
    issues = validate_model_instance(
        {"instance_id": "m27b1", "resource_id": "gpu-0", "servable_models": {"qwen3-27b": 4}}
    )
    assert issues == []


def test_validate_model_instance_rejects_empty_servable_models():
    issues = validate_model_instance(
        {"instance_id": "m27b1", "resource_id": "gpu-0", "servable_models": {}}
    )
    assert any("servable_models" in i for i in issues)


def test_validate_model_instance_rejects_non_positive_concurrency():
    issues = validate_model_instance(
        {"instance_id": "m", "resource_id": "gpu-0", "servable_models": {"qwen3-27b": 0}}
    )
    assert any("concurrency must be a positive integer" in i for i in issues)


def test_validate_model_instance_rejects_bool_concurrency():
    """bool is a subclass of int in Python -- must be explicitly excluded,
    matching this codebase's established pattern elsewhere (e.g. OutputPolicy)."""
    issues = validate_model_instance(
        {"instance_id": "m", "resource_id": "gpu-0", "servable_models": {"qwen3-27b": True}}
    )
    assert any("concurrency must be a positive integer" in i for i in issues)


def test_validate_model_instance_rejects_loaded_model_not_in_servable_models():
    issues = validate_model_instance(
        {
            "instance_id": "m", "resource_id": "gpu-0",
            "servable_models": {"qwen3-27b": 4}, "loaded_model": "gemma4",
        }
    )
    assert any("loaded_model must be a key of servable_models" in i for i in issues)


def test_model_instance_concurrency_for():
    instance = model_instance_from_dict(
        {"instance_id": "m", "resource_id": "gpu-0", "servable_models": {"qwen3-27b": 4}}
    )
    assert instance.concurrency_for("qwen3-27b") == 4
    assert instance.concurrency_for("unknown-model") is None


def test_model_instance_store_list_serving():
    """The exact query a profile naming a logical model resolves its
    compatible-instance set through."""
    store = ModelInstanceStore(
        [
            ModelInstance(instance_id="m27b1", resource_id="gpu-0", servable_models={"qwen3-27b": 4}),
            ModelInstance(instance_id="m27b2", resource_id="gpu-1", servable_models={"qwen3-27b": 4}),
            ModelInstance(instance_id="swap-0", resource_id="host-0", servable_models={"gemma4": 1}),
        ]
    )
    serving = {i.instance_id for i in store.list_serving("qwen3-27b")}
    assert serving == {"m27b1", "m27b2"}
    assert store.list_serving("nonexistent-model") == []


# ── CRUD API round-trip (the m27b1/m27b2 scenario that motivated AS105) ──

def test_two_instances_same_logical_model_different_gpus():
    create_compute_resource({"resource_id": "local-gpu-0", "kind": "local-gpu"})
    create_compute_resource({"resource_id": "local-gpu-1", "kind": "local-gpu"})
    create_model_instance({
        "instance_id": "m27b1", "resource_id": "local-gpu-0",
        "logical_model": "qwen3-27b", "servable_models": {"qwen3-27b": 4}, "loaded_model": "qwen3-27b",
    })
    create_model_instance({
        "instance_id": "m27b2", "resource_id": "local-gpu-1",
        "logical_model": "qwen3-27b", "servable_models": {"qwen3-27b": 4}, "loaded_model": "qwen3-27b",
    })

    serving = {i["instance_id"] for i in list_instances_serving("qwen3-27b")}
    assert serving == {"m27b1", "m27b2"}
    assert get_model_instance("m27b1")["logical_model"] == get_model_instance("m27b2")["logical_model"]


def test_llama_swap_style_multi_model_instance():
    """One instance, several servable models, one loaded at a time --
    concurrency differs per model on the same instance."""
    create_compute_resource({"resource_id": "llama-swap-host", "kind": "remote-host"})
    create_model_instance({
        "instance_id": "swap-endpoint-0",
        "resource_id": "llama-swap-host",
        "servable_models": {"qwen3.5-2b": 1, "gemma4-E4B": 1, "gemma4-E2B": 2},
        "loaded_model": "qwen3.5-2b",
    })
    instance = get_model_instance("swap-endpoint-0")
    assert instance["servable_models"]["gemma4-E2B"] == 2
    assert instance["servable_models"]["qwen3.5-2b"] == 1
    assert instance["loaded_model"] == "qwen3.5-2b"


def test_update_model_instance_concurrency():
    create_compute_resource({"resource_id": "gpu-0", "kind": "local-gpu"})
    create_model_instance({
        "instance_id": "m1", "resource_id": "gpu-0", "servable_models": {"m": 4},
    })
    updated = update_model_instance("m1", {"servable_models": {"m": 8}})
    assert updated["servable_models"]["m"] == 8
    assert get_model_instance("m1")["servable_models"]["m"] == 8


def test_delete_model_instance_removes_it():
    create_compute_resource({"resource_id": "gpu-0", "kind": "local-gpu"})
    create_model_instance({"instance_id": "m1", "resource_id": "gpu-0", "servable_models": {"m": 1}})
    delete_model_instance("m1")
    with pytest.raises(AudiaGenticError) as exc_info:
        get_model_instance("m1")
    assert exc_info.value.code == "RES-MINST-001"


def test_update_compute_resource_immutable_id():
    create_compute_resource({"resource_id": "r1", "kind": "local-gpu"})
    updated = update_compute_resource("r1", {"resource_id": "should-be-ignored", "kind": "remote-host"})
    assert updated["resource_id"] == "r1"
    assert updated["kind"] == "remote-host"


def test_delete_compute_resource_removes_it():
    create_compute_resource({"resource_id": "r1", "kind": "local-gpu"})
    delete_compute_resource("r1")
    with pytest.raises(AudiaGenticError) as exc_info:
        get_compute_resource("r1")
    assert exc_info.value.code == "RES-CRES-001"


def test_empty_store_when_no_file_exists():
    assert list_compute_resources() == []
    assert list_model_instances() == []


def test_load_compute_resources_rejects_unsupported_contract_version(tmp_path, monkeypatch):
    import yaml

    from audiagentic.components.agents.agents_paths import compute_resources_path

    path = compute_resources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"contract-version": "v99", "resources": []}), encoding="utf-8")
    with pytest.raises(AudiaGenticError) as exc_info:
        load_compute_resources()
    assert exc_info.value.code == "VAL-CRES-004"


def test_rig_worked_example_expresses_cleanly():
    """AS105 step 7's validation exercise: one resource, one instance, one
    servable model with concurrency 1 -- must model with zero special-casing."""
    create_compute_resource({"resource_id": "cli-embedded-rig", "kind": "local-gpu"})
    instance = create_model_instance({
        "instance_id": "rig-embedded",
        "resource_id": "cli-embedded-rig",
        "logical_model": "audiagentic-rig",
        "servable_models": {"audiagentic-rig": 1},
        "loaded_model": "audiagentic-rig",
    })
    assert instance["servable_models"] == {"audiagentic-rig": 1}
    serving = list_instances_serving("audiagentic-rig")
    assert len(serving) == 1
    assert serving[0]["instance_id"] == "rig-embedded"


def test_compute_resource_and_model_instance_do_not_consult_project_tier(tmp_path):
    """AS105's closed override hazard: these APIs take no project_root
    parameter at all -- a project cannot redefine shared hardware capacity
    by declaring the same namespace in its own .audiagentic/config/."""
    import inspect

    from audiagentic.components.agents.models import compute_resource_api, model_instance_api

    for fn in (
        compute_resource_api.load_compute_resources,
        compute_resource_api.create_compute_resource,
        model_instance_api.load_model_instances,
        model_instance_api.create_model_instance,
    ):
        params = inspect.signature(fn).parameters
        assert "project_root" not in params, f"{fn.__name__} must not accept project_root"
