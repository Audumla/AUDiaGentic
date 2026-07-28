from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from audiagentic.runtime.rig import service
from audiagentic.runtime.rig.embedded.launch import LaunchPlan


def _plan(tmp_path: Path) -> LaunchPlan:
    return LaunchPlan(
        bin_dir=tmp_path,
        binary=tmp_path / "llama-server",
        server_dir=tmp_path,
        model_path=tmp_path / "model.gguf",
        model_arg="model.gguf",
        device=None,
        profile=SimpleNamespace(name="profile", server_cfg={}, chat_template_kwargs={}),
        server_cfg={},
    )


def test_start_projects_one_profile_bound_managed_service(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class Lifecycle:
        def __init__(self, store, hooks) -> None:
            captured["store"] = store
            captured["hooks"] = hooks

        def start_or_attach(self, declaration, **kwargs):
            captured["declaration"] = declaration
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                record=SimpleNamespace(owner_epoch="epoch"),
                lease=SimpleNamespace(lease_id="lease"),
            )

    monkeypatch.setattr(service, "ManagedServiceLifecycle", Lifecycle)
    monkeypatch.setattr(service, "prepare_launch", lambda **_kwargs: _plan(tmp_path))
    monkeypatch.setattr(service.RigAttachment, "start_renewal", lambda self: None)

    attachment = service.start_or_attach_embedded_rig(
        profile_name="profile", rig_port=42001, model_id="audiagentic-rig"
    )

    declaration = captured["declaration"]
    assert attachment.endpoint == "http://127.0.0.1:42001/v1"
    assert declaration.key == service.RIG_SERVICE_KEY
    assert declaration.endpoint.address == "127.0.0.1:42001/v1"
    assert declaration.protocol_version == service._protocol_version("profile")
    assert "--alias" in declaration.process.command


def test_profile_identity_is_not_shared_between_models() -> None:
    assert service._protocol_version("model-a") != service._protocol_version("model-b")


def test_release_does_not_stop_while_another_lease_is_active(monkeypatch) -> None:
    calls: list[str] = []

    class Store:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def release_lease(self, *_args, **_kwargs):
            calls.append("release")
            return SimpleNamespace(active_lease_count=1)

    monkeypatch.setattr(service, "ManagedServiceStore", Store)
    attachment = service.RigAttachment("http://127.0.0.1:42001/v1", "m", "lease", "epoch")
    service.release_embedded_rig(attachment)
    assert calls == ["release"]
