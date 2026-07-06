"""End-to-end regression tests for component profile switching (CP07).

Validates layered profile discovery, base-only fallback, cross-profile guard
(VAL-COMP-010), and idempotent re-registration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_descriptor


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


BASE_COMPONENT_YAML = """\
type: component
id: base-component
display-name: Base Component
description: A base-level component always available
detection-marker: .audiagentic/components/base-component.yaml
"""

PROFILE_COMPONENT_YAML = """\
type: component
id: profile-component
display-name: Profile Component
description: A profile-specific component
detection-marker: .audiagentic/components/profile-component.yaml
"""


def _build_layered_structure(tmp_path: Path, profile_name: str):
    """Create base + profile directory tree under tmp_path and return (base_dir, tmp_path)."""
    base_dir = tmp_path / "base-components"

    _write(base_dir / "base-component.yaml", BASE_COMPONENT_YAML)

    profile_dir = tmp_path / ".audiagentic" / profile_name / "components"
    _write(profile_dir / "profile-component.yaml", PROFILE_COMPONENT_YAML)

    return base_dir, tmp_path


class TestProfileLayering:
    """CP07 scenario 1: profile loads its components layered over base components."""

    def test_profile_loads_both_base_and_profile_components(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir, _ = _build_layered_structure(tmp_path, "test-profile")

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "test-profile")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        monkeypatch.chdir(str(tmp_path))

        descriptors = register_all_components()

        ids = [d.component_id for d in descriptors]
        assert "base-component" in ids
        assert "profile-component" in ids

        base_desc = get_descriptor("base-component")
        profile_desc = get_descriptor("profile-component")
        assert base_desc is not None
        assert profile_desc is not None
        assert base_desc.display_name == "Base Component"
        assert profile_desc.display_name == "Profile Component"


class TestBaseOnly:
    """CP07 scenario 2: no profile yields base-only behavior unchanged."""

    def test_no_profile_loads_base_components_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir = tmp_path / "base-components"
        _write(base_dir / "base-component.yaml", BASE_COMPONENT_YAML)

        monkeypatch.delenv("AUDIAGENTIC_COMPONENT_PROFILE", raising=False)
        descriptors = register_all_components([base_dir])

        ids = [d.component_id for d in descriptors]
        assert ids == ["base-component"]
        base_desc = get_descriptor("base-component")
        assert base_desc is not None
        assert base_desc.display_name == "Base Component"

    def test_no_profile_ignores_profile_directory(self, tmp_path: Path) -> None:
        """Profile components exist on disk but without the env var they are not loaded."""
        base_dir = tmp_path / "base-components"
        _write(base_dir / "base-component.yaml", BASE_COMPONENT_YAML)

        profile_dir = tmp_path / ".audiagentic" / "orphan-profile" / "components"
        _write(profile_dir / "profile-component.yaml", PROFILE_COMPONENT_YAML)

        descriptors = register_all_components([base_dir])

        ids = [d.component_id for d in descriptors]
        assert ids == ["base-component"]
        assert get_descriptor("profile-component") is None


class TestCwdIndependentResolution:
    """RV117/RV127: profile resolution must follow the project root, not cwd."""

    def test_profile_resolves_via_repo_root_env_with_unrelated_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With AUDIAGENTIC_REPO_ROOT pointing at the project, the profile
        layer must load even when cwd is a completely unrelated directory."""
        project = tmp_path / "project"
        base_dir, _ = _build_layered_structure(project, "env-profile")

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "env-profile")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(project))
        monkeypatch.chdir(str(elsewhere))

        descriptors = register_all_components()

        ids = [d.component_id for d in descriptors]
        assert "base-component" in ids
        assert "profile-component" in ids

    def test_profile_resolves_from_nested_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cwd in a nested subdirectory of the project must still find the
        project root by walking up to the .audiagentic marker."""
        base_dir, _ = _build_layered_structure(tmp_path, "nested-profile")
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "nested-profile")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        monkeypatch.chdir(str(nested))

        descriptors = register_all_components()

        ids = [d.component_id for d in descriptors]
        assert "base-component" in ids
        assert "profile-component" in ids


class TestCrossProfileGuard:
    """CP07 scenario 3: switching profiles mid-process raises VAL-COMP-010."""

    def test_switching_profile_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        base_dir, _ = _build_layered_structure(tmp_path, "profile-a")

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "profile-a")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        monkeypatch.chdir(str(tmp_path))

        register_all_components()

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "profile-b")

        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError) as exc_info:
            register_all_components()

        assert exc_info.value.code == "VAL-COMP-010"
        assert "Cannot switch component profile mid-process" in exc_info.value.message


class TestIdempotentReregistration:
    """CP07 scenario 4: same-profile re-registration succeeds silently."""

    def test_same_profile_reregister_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir, _ = _build_layered_structure(tmp_path, "stable-profile")

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "stable-profile")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        monkeypatch.chdir(str(tmp_path))

        first = register_all_components()
        second = register_all_components()

        assert [d.component_id for d in first] == [d.component_id for d in second]


class TestDuplicateIdResolution:
    """CP07 additional: profile-layer duplicate ID wins over base."""

    def test_profile_descriptor_overrides_base_same_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir = tmp_path / "base-components"
        _write(
            base_dir / "shared-component.yaml",
            "type: component\nid: shared-component\ndisplay-name: Base Version\n"
            "detection-marker: .audiagentic/components/shared-component.yaml\n",
        )

        profile_dir = tmp_path / ".audiagentic" / "override-profile" / "components"
        _write(
            profile_dir / "shared-component.yaml",
            "type: component\nid: shared-component\ndisplay-name: Profile Override\n"
            "detection-marker: .audiagentic/components/shared-component.yaml\n",
        )

        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "override-profile")
        monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", str(base_dir))
        monkeypatch.delenv("AUDIAGENTIC_REPO_ROOT", raising=False)
        monkeypatch.chdir(str(tmp_path))

        register_all_components()

        desc = get_descriptor("shared-component")
        assert desc is not None
        assert desc.display_name == "Profile Override"
