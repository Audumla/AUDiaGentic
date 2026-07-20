from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.harness.pi.install import install_to


def test_pi_recipe_declares_managed_packages_and_acp_runtime() -> None:
    from audiagentic.runtime.harness.pi.install import _package_recipe

    assert _package_recipe({"agent": {
        "packages": {
            "cli": "example/pi",
            "mcp_adapter": "example/pi-mcp",
            "acp": "example/pi-acp",
        },
        "acp_version": "1.2.3",
        "runtime_extra": "acp",
    }}) == ("example/pi", "example/pi-mcp", "example/pi-acp", "1.2.3", "acp")


def test_pi_recipe_defaults_preserve_existing_overrides() -> None:
    from audiagentic.runtime.harness.pi.install import _package_recipe

    assert _package_recipe({"agent": {}}) == (
        "@earendil-works/pi-coding-agent",
        "pi-mcp-adapter",
        "pi-acp",
        "0.0.31",
        "acp",
    )


def test_install_to_provisions_embedded_rig_in_docker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "harness"
    project_root = tmp_path / "project"
    src_root = tmp_path / "src" / "audiagentic"
    fixture_model = tmp_path / "tests" / "unit" / "runtime" / "Qwen3.5-0.8B-UD-Q5_K_XL.gguf"
    project_root.mkdir(parents=True)
    src_root.mkdir(parents=True)
    fixture_model.parent.mkdir(parents=True, exist_ok=True)
    fixture_model.write_bytes(b"gguf")

    calls: list[Path] = []

    monkeypatch.setenv("AUDIAGENTIC_DOCKER_TESTS", "1")
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._c._npm",
        lambda: "npm",
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._c.load_pi_config",
        lambda project_root=None: {"agent": {"version": "latest", "mcp_adapter_version": "latest"}},
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._c.load_harness_config",
        lambda project_root=None: {},
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.subprocess.run",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._validate_agent_install",
        lambda npm_dir: None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.apply_lockdown_patches",
        lambda npm_dir, project_root=None: None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install.materialize_agent_config",
        lambda target, harness_cfg, project_root=None: None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.install._provision_embedded_rig",
        lambda target, project_root=None: calls.append(target),
    )

    rc = install_to(target, project_root=project_root)

    assert rc == 0
    assert calls == [target]


def test_install_to_seeds_test_model_when_repo_fixture_exists(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    project_root = repo_root / "tmp" / "project"
    fixture_model = repo_root / "tests" / "unit" / "runtime" / "Qwen3.5-0.8B-UD-Q5_K_XL.gguf"
    target = repo_root / "runtime"
    project_root.mkdir(parents=True)
    (repo_root / "src" / "audiagentic").mkdir(parents=True)
    fixture_model.parent.mkdir(parents=True, exist_ok=True)
    fixture_model.write_bytes(b"gguf")

    from audiagentic.runtime.harness.pi.install import _seed_test_model

    _seed_test_model(target, project_root)

    seeded = target / "rig" / "bin" / "models" / "Qwen3.5-0.8B.Q8_0.gguf"
    assert seeded.exists()
    assert seeded.read_bytes() == b"gguf"
