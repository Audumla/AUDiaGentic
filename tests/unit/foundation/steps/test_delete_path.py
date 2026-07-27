from pathlib import Path

from audiagentic.foundation.steps import DeletePathStep


class TestDeletePathStep:
    """Tests for DeletePathStep — file remove, recursive dir remove, compensate."""

    def test_removes_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("hello")

        step = DeletePathStep(id="rm", path=str(target))
        result = step.run({})

        assert result.status == "ok"
        assert not target.exists()
        assert result.outputs["existed"] is True

    def test_noop_when_path_absent(self, tmp_path: Path) -> None:
        step = DeletePathStep(id="rm", path=str(tmp_path / "missing.txt"))
        result = step.run({})

        assert result.status == "ok"
        assert result.outputs["existed"] is False

    def test_fails_dir_without_recursive(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        step = DeletePathStep(id="rm", path=str(subdir), recursive=False)
        result = step.run({})

        assert result.status == "failed"
        assert subdir.exists()

    def test_removes_dir_with_recursive(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "a.txt").write_text("a")

        step = DeletePathStep(id="rm", path=str(subdir), recursive=True)
        result = step.run({})

        assert result.status == "ok"
        assert not subdir.exists()
        assert result.outputs["existed"] is True

    def test_compensate_restores_file(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        original_content = b"hello world"
        target.write_bytes(original_content)

        step = DeletePathStep(id="rm", path=str(target))
        run_result = step.run({})
        assert run_result.status == "ok"
        assert not target.exists()

        comp_result = step.compensate({})
        assert comp_result.status == "ok"
        assert comp_result.outputs["restored"] is True
        assert target.read_bytes() == original_content

    def test_compensate_skipped_when_recursive(self, tmp_path: Path) -> None:
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        step = DeletePathStep(id="rm", path=str(subdir), recursive=True)
        step.run({})

        comp_result = step.compensate({})
        assert comp_result.status == "skipped"

    def test_compensate_skipped_when_run_not_called(self, tmp_path: Path) -> None:
        step = DeletePathStep(id="rm", path=str(tmp_path / "file.txt"))
        comp_result = step.compensate({})

        assert comp_result.status == "skipped"

    def test_expanduser_in_path(self, monkeypatch, tmp_path: Path) -> None:
        # Test that ~ expands correctly via expanduser

        target = tmp_path / "file.txt"
        target.write_text("data")

        class FakePath(Path):
            def expanduser(self):
                p = super().expanduser()
                if str(p).startswith("~/"):
                    return p.with_name(str(tmp_path))
                return p

        from audiagentic.foundation.steps import structured

        original_path = structured.Path
        monkeypatch.setattr(structured, "Path", FakePath)
        try:
            step = DeletePathStep(id="rm", path=str(tmp_path / "file.txt"))
            result = step.run({})
            assert result.status == "ok"
            assert not target.exists()
        finally:
            monkeypatch.setattr(structured, "Path", original_path)


class TestDeletePathStepRecipe:
    """End-to-end recipe test for delete-path step type."""

    def test_delete_path_via_factory(self, tmp_path: Path) -> None:
        from audiagentic.foundation.steps.factory import build_step

        target = tmp_path / "file.txt"
        target.write_text("remove me")

        data = {
            "type": "delete-path",
            "id": "rm-file",
            "path": str(target),
        }
        step = build_step(data)
        assert isinstance(step, DeletePathStep)
        result = step.run({})
        assert result.status == "ok"

    def test_delete_path_with_params(self, tmp_path: Path) -> None:
        from audiagentic.foundation.steps.factory import build_step

        target = tmp_path / "file.txt"
        target.write_text("remove me")

        data = {
            "type": "delete-path",
            "id": "rm-file",
            "path": "{TARGET_PATH}",
            "recursive": False,
        }
        step = build_step(data, params={"TARGET_PATH": str(target)})
        assert isinstance(step, DeletePathStep)
        result = step.run({})
        assert result.status == "ok"

    def test_delete_path_schema_registered(self) -> None:
        from audiagentic.foundation.steps.factory import registered_types, step_schema

        assert "delete-path" in registered_types()
        schema = step_schema("delete-path")
        assert schema is not None
        assert "path" in schema["required"]
        assert schema["properties"]["recursive"]["type"] == "boolean"

    def test_compensate_restores_parent_dirs(self, tmp_path: Path) -> None:
        import shutil

        target = tmp_path / "deep" / "nested" / "file.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")

        step = DeletePathStep(id="rm", path=str(target))
        step.run({})

        # Remove parent dirs too to test mkdir on compensate
        shutil.rmtree(tmp_path / "deep")

        comp_result = step.compensate({})
        assert comp_result.status == "ok"
        assert target.read_bytes() == b"data"
