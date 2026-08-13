from __future__ import annotations

import sys
from pathlib import Path

import pytest

from audiagentic.components.agent_jobs.prompt_templates import (
    load_prompt_from_file,
    render_prompt_template,
)
from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
)
from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
)


@pytest.fixture(autouse=True, scope="session")
def _load_error_resolutions() -> None:
    config_dirs = [
        Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    ]
    load_all_error_resolutions(config_dirs)


class TestLoadPromptFromFile:
    """EDJ11 — load prompt templates from explicit file paths."""

    def test_load_relative_path(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / ".audiagentic" / "prompts" / "jobs"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        tmpl_file = tmpl_dir / "greet.md"
        tmpl_file.write_text("Hello {name}!\n", encoding="utf-8")

        content, resolved = load_prompt_from_file(
            tmp_path, ".audiagentic/prompts/jobs/greet.md", source_label="job-runner"
        )
        assert "Hello {name}" in content
        assert resolved == tmpl_file.resolve()

    def test_load_absolute_path_within_root(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        abs_file = tmpl_dir / "welcome.md"
        abs_file.write_text("Welcome aboard.\n", encoding="utf-8")

        content, resolved = load_prompt_from_file(
            tmp_path, str(abs_file), source_label=""
        )
        assert "Welcome aboard" in content
        assert resolved == abs_file.resolve()

    def test_load_symlink_within_root(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / ".audiagentic" / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        real_file = tmpl_dir / "real.md"
        real_file.write_text("Real content.\n", encoding="utf-8")
        link_file = tmpl_dir / "link.md"
        try:
            link_file.symlink_to(real_file)
        except OSError:
            pytest.skip("symlink creation requires elevated privileges")

        content, resolved = load_prompt_from_file(
            tmp_path, str(link_file), source_label=""
        )
        assert "Real content" in content
        # Resolved path points to the real target after symlink resolution
        assert resolved.is_file()

    def test_missing_file_raises_IO_PTMPL_001(self, tmp_path: Path) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            load_prompt_from_file(
                tmp_path, ".audiagentic/prompts/missing.md", source_label="test"
            )
        assert exc_info.value.code == "IO-PTMPL-001"

    def test_path_traversal_escape_raises_IO_PATH_001(self, tmp_path: Path) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            load_prompt_from_file(
                tmp_path, "../../../etc/passwd", source_label="test"
            )
        assert exc_info.value.code == "IO-PATH-001"

    def test_absolute_path_outside_root_raises_IO_PATH_001(self, tmp_path: Path) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            load_prompt_from_file(
                tmp_path, "/etc/shadow", source_label="test"
            )
        assert exc_info.value.code == "IO-PATH-001"

    def test_windows_absolute_path_outside_root_raises_IO_PATH_001(
        self, tmp_path: Path
    ) -> None:
        if sys.platform != "win32":
            pytest.skip("Windows-only test")
        with pytest.raises(AudiaGenticError) as exc_info:
            load_prompt_from_file(
                tmp_path, "C:\\Windows\\System32\\config\\SYSTEM", source_label="test"
            )
        assert exc_info.value.code == "IO-PATH-001"

    def test_utf8_content_loads(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        tmpl_file = tmpl_dir / "unicode.md"
        tmpl_file.write_text("你好 {name}！\n", encoding="utf-8")

        content, _ = load_prompt_from_file(
            tmp_path, "prompts/unicode.md", source_label=""
        )
        assert "你好" in content


class TestRenderPromptTemplate:
    """EDJ11 — render prompt templates with dotted-path placeholders."""

    def test_simple_placeholder(self) -> None:
        result = render_prompt_template(
            "Review {subject} now.", {"subject": "PR #42"}
        )
        assert "PR #42" in result

    def test_flat_key_from_dict(self) -> None:
        result = render_prompt_template("ID is {id}.", {"id": "A1"})
        assert "A1" in result

    def test_dotted_path_lookup(self) -> None:
        template = "Item {event.payload.item_id} ({event.payload.type})"
        vals = {"event": {"payload": {"item_id": 42, "type": "create"}}}
        result = render_prompt_template(template, vals)
        assert "42" in result and "create" in result

    def test_hyphenated_key(self) -> None:
        result = render_prompt_template(
            "{project-root}", {"project-root": "/home/user/project"}
        )
        assert "/home/user/project" in result


class TestPathSafetyIntegration:
    """Verify that ensure_contained handles edge cases correctly."""

    def test_empty_relative_path_is_root(self, tmp_path: Path) -> None:
        from audiagentic.foundation.paths.safety import ensure_contained

        resolved = ensure_contained(tmp_path, "")
        assert resolved == tmp_path.resolve()

    def test_single_dot_normalizes_to_root(self, tmp_path: Path) -> None:
        from audiagentic.foundation.paths.safety import ensure_contained

        resolved = ensure_contained(tmp_path, ".")
        assert resolved == tmp_path.resolve()

    def test_deep_relative_within_root(self, tmp_path: Path) -> None:
        from audiagentic.foundation.paths.safety import ensure_contained

        deep_dir = tmp_path / "a" / "b" / "c"
        deep_dir.mkdir(parents=True, exist_ok=True)
        resolved = ensure_contained(tmp_path, "a/b/c/../c/target.md")
        assert str(resolved).endswith("a/b/c/target.md") or str(resolved).endswith(
            r"a\b\c\target.md"
        )

    def test_traversal_to_root_boundary(self, tmp_path: Path) -> None:
        from audiagentic.foundation.paths.safety import ensure_contained

        sub = tmp_path / "sub"
        sub.mkdir(parents=True, exist_ok=True)
        # From inside sub dir, one level up should still be in root
        resolved = ensure_contained(tmp_path, "sub/../other")
        assert resolved.parent == tmp_path.resolve()
