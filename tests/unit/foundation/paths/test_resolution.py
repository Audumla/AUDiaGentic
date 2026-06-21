from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.resolution import (
    build_layered_path_map,
    load_layered_mapping,
    resolve_existing_dir,
    resolve_existing_file,
    resolve_required_file,
)


def test_load_layered_mapping_merges_default_global_local(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg.yaml"
    global_cfg = tmp_path / "global.yaml"
    local_cfg = tmp_path / "local.yaml"
    pkg.write_text("a: 1\nnested:\n  pkg: true\n  shared: pkg\n", encoding="utf-8")
    global_cfg.write_text("nested:\n  global: true\n  shared: global\n", encoding="utf-8")
    local_cfg.write_text("nested:\n  local: true\n  shared: local\n", encoding="utf-8")

    resolved = load_layered_mapping(
        package_default_path=pkg,
        user_global_path=global_cfg,
        project_local_path=local_cfg,
    )

    assert resolved == {
        "a": 1,
        "nested": {
            "pkg": True,
            "global": True,
            "local": True,
            "shared": "local",
        },
    }


def test_load_layered_mapping_respects_exclusive_local(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg.yaml"
    global_cfg = tmp_path / "global.yaml"
    local_cfg = tmp_path / "local.yaml"
    pkg.write_text("shared: pkg\n", encoding="utf-8")
    global_cfg.write_text("shared: global\n", encoding="utf-8")
    local_cfg.write_text("exclusive_local: true\nshared: local\n", encoding="utf-8")

    resolved = load_layered_mapping(
        package_default_path=pkg,
        user_global_path=global_cfg,
        project_local_path=local_cfg,
    )

    assert resolved == {"shared": "local"}


def test_resolve_existing_file_prefers_project_local(tmp_path: Path) -> None:
    pkg_root = tmp_path / "pkg"
    global_root = tmp_path / "global"
    project_root = tmp_path / "project"
    for root, text in ((pkg_root, "pkg"), (global_root, "global"), (project_root, "local")):
        (root / "conf").mkdir(parents=True)
        (root / "conf" / "settings.yaml").write_text(text, encoding="utf-8")

    path_map = build_layered_path_map(
        package_root=pkg_root,
        package_default="conf/settings.yaml",
        user_global_root=global_root,
        user_global="conf/settings.yaml",
        project_root=project_root,
        project_local="conf/settings.yaml",
    )

    assert resolve_existing_file(path_map) == project_root / "conf" / "settings.yaml"


def test_resolve_existing_dir_falls_back_to_user_global(tmp_path: Path) -> None:
    global_root = tmp_path / "global"
    (global_root / "rig" / "bin").mkdir(parents=True)

    path_map = build_layered_path_map(
        user_global_root=global_root,
        user_global="rig/bin",
        project_root=tmp_path / "project",
        project_local="provisioning/rig/embedded/bin",
    )

    assert resolve_existing_dir(path_map) == global_root / "rig" / "bin"


def test_resolve_required_file_reports_candidates(tmp_path: Path) -> None:
    path_map = build_layered_path_map(
        user_global_root=tmp_path / "global",
        user_global="rig/missing.gguf",
        project_root=tmp_path / "project",
        project_local="provisioning/rig/embedded/missing.gguf",
    )

    try:
        resolve_required_file(path_map, label="Model")
    except AudiaGenticError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected AudiaGenticError")

    assert "Model not found. Checked:" in message
    assert "provisioning\\rig\\embedded\\missing.gguf" in message
    assert "global\\rig\\missing.gguf" in message
