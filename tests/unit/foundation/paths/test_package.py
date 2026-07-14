from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths import package as package_paths


def test_find_repo_root_falls_back_to_installed_package_parent(tmp_path: Path, monkeypatch) -> None:
    package_file = tmp_path / "site-packages" / "audiagentic" / "foundation" / "paths" / "package.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("# package marker\n", encoding="utf-8")

    monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
    monkeypatch.setattr(package_paths, "__file__", str(package_file))

    assert package_paths.find_repo_root(package_file) == tmp_path / "site-packages"


def test_source_root_is_package_import_root() -> None:
    assert package_paths.SRC_ROOT == package_paths.PACKAGE_ROOT.parent
    assert package_paths.PACKAGE_ROOT.name == "audiagentic"
