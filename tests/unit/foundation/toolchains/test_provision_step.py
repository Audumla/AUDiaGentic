from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.provision_steps import (
    ConfigSetStep,
    ManagedBlockStep,
    ShellProvisionStep,
    WriteFileStep,
    _substitute,
    provision_step_from_dict,
)

# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------


class TestSubstitute:
    def test_replaces_placeholder_in_string(self):
        result = _substitute("hello {NAME}", {"NAME": "world"}, "root")
        assert result == "hello world"

    def test_replaces_multiple_placeholders(self):
        result = _substitute("{A}-{B}", {"A": "1", "B": "2"})
        assert result == "1-2"

    def test_passes_through_non_string(self):
        assert _substitute(42, {}) == 42
        assert _substitute(True, {}) is True
        assert _substitute(None, {}) is None

    def test_recurses_into_list(self):
        result = _substitute(["a-{X}", "b"], {"X": "1"})
        assert result == ["a-1", "b"]

    def test_recurses_into_dict(self):
        result = _substitute({"key": "{V}"}, {"V": "42"})
        assert result == {"key": "42"}

    def test_nested_dict_list(self):
        data = {"items": [{"url": "{URL}/path"}]}
        result = _substitute(data, {"URL": "https://example.com"})
        assert result == {"items": [{"url": "https://example.com/path"}]}

    def test_unknown_placeholder_raises(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            _substitute("{MISSING}", {}, "test")
        assert exc_info.value.code == "VAL-PSTEP-002"

    def test_repeated_placeholder_usage(self):
        result = _substitute("{X} and {X}", {"X": "a"})
        assert result == "a and a"


# ---------------------------------------------------------------------------
# ShellProvisionStep
# ---------------------------------------------------------------------------


class TestShellProvisionStep:
    def test_success_returns_ok(self, monkeypatch):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="hello", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="test-shell",
            command=["python", "-c", "print('hello')"],
        )
        result = step.run({})
        assert result.status == "ok"

    def test_failure_returns_failed(self, monkeypatch):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="error")

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="fail-shell",
            command=["python", "-c", "import sys; sys.exit(1)"],
        )
        result = step.run({})
        assert result.status == "failed"

    def test_revert_with_command(self, monkeypatch):
        call_log = []

        def fake_run(command, **kwargs):
            call_log.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="rev-shell",
            command=["python", "-c", "print('forward')"],
            revert_command=["python", "-c", "print('reverse')"],
        )
        fwd = step.run({})
        assert fwd.status == "ok"
        rev = step.revert({})
        assert rev.status == "ok"
        assert len(call_log) == 2

    def test_revert_without_command_skipped(self):
        step = ShellProvisionStep(
            id="no-rev",
            command=["echo", "hello"],
        )
        result = step.revert({})
        assert result.status == "skipped"
        assert "no revert declared" in (result.reason or "")

    def test_dry_run_returns_planned(self):
        step = ShellProvisionStep(
            id="dry",
            command=["echo", "test"],
        )
        result = step.dry_run({})
        assert result.status == "planned"
        assert result.outputs["shell"] is False

    def test_shell_true_mode(self):
        step = ShellProvisionStep(
            id="shell-mode",
            command="echo hello_world",
            shell=True,
        )
        result = step.run({})
        assert result.status == "ok"

    def test_dry_run_shell_true(self):
        step = ShellProvisionStep(
            id="dry-shell",
            command="echo test",
            shell=True,
        )
        result = step.dry_run({})
        assert result.status == "planned"
        assert result.outputs["shell"] is True

    def test_command_not_found(self):
        step = ShellProvisionStep(
            id="notfound",
            command=["__nonexistent_binary_xyz__"],
        )
        result = step.run({})
        assert result.status == "failed"

    def test_shell_stdout_token_is_redacted(self, monkeypatch):
        """RS16: token-like strings in stdout ARE redacted."""
        fake_stdout = "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 0, stdout=fake_stdout, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="token-redacted",
            command=["python", "-c", "print('sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')"],
        )
        result = step.run({})
        assert result.status == "ok"
        stdout = result.outputs.get("stdout", "")
        assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in stdout, (
            "Token must NOT be present in stdout after redaction"
        )
        assert "[REDACTED]" in stdout, (
            "Redaction marker must be present when a token is found"
        )

    def test_shell_failure_reason_is_redacted(self, monkeypatch):
        """RS16: failure reason must NOT carry raw secret text."""
        fake_stdout = "ERROR: token=sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa exposed in output\n"

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 1, stdout=fake_stdout, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="fail-redacted",
            command=["python", "-c", "import sys; sys.exit(1)"],
        )
        result = step.run({})
        assert result.status == "failed"
        reason = result.reason or ""
        assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in reason, (
            "Raw secret must NOT appear in failure reason after redaction"
        )
        assert "[REDACTED]" in reason, (
            "Redaction marker must be present in failure reason when secrets are found"
        )

    def test_shell_env_secret_is_redacted(self, monkeypatch):
        """RS16: env secrets echoed to stdout MUST be redacted."""
        secret_value = "sk-secret-value-12345678901234567890"

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 0, stdout=secret_value + "\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        step = ShellProvisionStep(
            id="env-redacted",
            command=["python", "-c", "import os; print(os.environ['API_KEY'])"],
            env={"API_KEY": secret_value},
        )
        result = step.run({})
        assert result.status == "ok"
        stdout = result.outputs.get("stdout", "")
        assert secret_value not in stdout, (
            "Secret value from env must NOT appear in stdout after redaction"
        )
        assert "[REDACTED]" in stdout, (
            "Redaction marker must be present when env-sourced secrets are detected"
        )


# ---------------------------------------------------------------------------
# CompensatingSequence aggregation leak
# ---------------------------------------------------------------------------

class TestCompensatingSequenceOutput:
    def test_compensating_sequence_redacts_step_output(self, monkeypatch):
        """RS16: CompensatingSequence aggregates REDACTED step outputs."""
        from audiagentic.foundation.toolchains.provision_steps.sequence import CompensatingSequence

        secret_token = "sk-comp-secret-abcdefghij1234567890"

        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(
                command, 0, stdout=f"result: {secret_token}\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        steps = [
            ShellProvisionStep(
                id="step-a",
                command=["python", "-c", "print('token')"],
            ),
            ShellProvisionStep(
                id="step-b",
                command=["python", "-c", "print('more')"],
            ),
        ]
        seq = CompensatingSequence(steps, id="agg-test")
        result = seq.run({})

        assert result.status == "ok"
        steps_output = result.outputs.get("steps", [])
        all_stdout_values = []
        for step_info in steps_output:
            step_outputs = step_info.get("outputs", {})
            if "stdout" in step_outputs:
                all_stdout_values.append(step_outputs["stdout"])

        combined_stdout = "\n".join(all_stdout_values)
        assert secret_token not in combined_stdout, (
            "Secret token must NOT appear in aggregated sequence output after redaction"
        )
        assert "[REDACTED]" in combined_stdout, (
            "Redaction marker must be present in aggregated output when secrets are found"
        )


# ---------------------------------------------------------------------------
# ConfigSetStep
# ---------------------------------------------------------------------------


class TestConfigSetStep:
    def test_creates_missing_key(self, tmp_path):
        cfg = tmp_path / "config.json"
        step = ConfigSetStep(
            id="set-key",
            path=str(cfg),
            key_path=("server", "url"),
            value="https://example.com",
        )
        result = step.run({})
        assert result.status == "ok"
        data = json.loads(cfg.read_text())
        assert data["server"]["url"] == "https://example.com"

    def test_overwrites_existing_key(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"server": {"url": "old"}}), encoding="utf-8")
        step = ConfigSetStep(
            id="overwrite",
            path=str(cfg),
            key_path=("server", "url"),
            value="https://new.com",
        )
        result = step.run({})
        assert result.status == "ok"
        data = json.loads(cfg.read_text())
        assert data["server"]["url"] == "https://new.com"

    def test_revert_restores_prior(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"key": "original"}), encoding="utf-8")
        step = ConfigSetStep(
            id="rev-key",
            path=str(cfg),
            key_path=("key",),
            value="modified",
        )
        step.run({})
        result = step.revert({})
        assert result.status == "ok"
        data = json.loads(cfg.read_text())
        assert data["key"] == "original"

    def test_revert_before_run_skipped(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"keep": True}), encoding="utf-8")
        step = ConfigSetStep(
            id="no-run",
            path=str(cfg),
            key_path=("new_key",),
            value="val",
        )
        result = step.revert({})
        assert result.status == "skipped"

    def test_revert_new_key_removes(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({}), encoding="utf-8")
        step = ConfigSetStep(
            id="new-key",
            path=str(cfg),
            key_path=("added",),
            value="yes",
        )
        step.run({})
        assert "added" in json.loads(cfg.read_text())
        step.revert({})
        assert "added" not in json.loads(cfg.read_text())

    def test_dry_run(self, tmp_path):
        cfg = tmp_path / "config.json"
        step = ConfigSetStep(
            id="dry-cfg",
            path=str(cfg),
            key_path=("a", "b"),
            value="v",
        )
        result = step.dry_run({})
        assert result.status == "planned"
        assert not cfg.exists()

    def test_registry_integration(self, tmp_path):
        cfg = tmp_path / "config.json"
        registry = MagicMock()
        step = ConfigSetStep(
            id="reg-cfg",
            path=str(cfg),
            key_path=("k",),
            value="v",
            registry=registry,
            recipe_id="test-recipe",
        )
        step.run({})
        assert registry.register.called
        call_kwargs = registry.register.call_args[1]
        assert "changes" in call_kwargs


# ---------------------------------------------------------------------------
# ManagedBlockStep
# ---------------------------------------------------------------------------


class TestManagedBlockStep:
    def test_run_applies_block(self, tmp_path):
        target = tmp_path / "file.txt"
        step = ManagedBlockStep(
            id="block-step",
            path=str(target),
            block_id="my-block",
            content="line1\nline2",
        )
        result = step.run({})
        assert result.status == "ok"
        content = target.read_text()
        assert ">>> audiagentic:my-block >>>" in content
        assert "line1" in content

    def test_revert_removes_block(self, tmp_path):
        target = tmp_path / "file.txt"
        step = ManagedBlockStep(
            id="rev-block",
            path=str(target),
            block_id="rb",
            content="managed",
        )
        step.run({})
        assert "managed" in target.read_text()
        result = step.revert({})
        assert result.status == "ok"
        assert "managed" not in target.read_text()

    def test_revert_before_run_skipped(self, tmp_path):
        step = ManagedBlockStep(
            id="no-run-block",
            path=str(tmp_path / "x.txt"),
            block_id="x",
            content="c",
        )
        result = step.revert({})
        assert result.status == "skipped"

    def test_dry_run(self, tmp_path):
        step = ManagedBlockStep(
            id="dry-block",
            path=str(tmp_path / "y.txt"),
            block_id="y",
            content="c",
        )
        result = step.dry_run({})
        assert result.status == "planned"


# ---------------------------------------------------------------------------
# WriteFileStep
# ---------------------------------------------------------------------------


class TestWriteFileStep:
    def test_creates_new_file(self, tmp_path):
        target = tmp_path / "new.txt"
        step = WriteFileStep(
            id="write-new",
            path=str(target),
            content="hello",
        )
        result = step.run({})
        assert result.status == "ok"
        assert target.read_text() == "hello"

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "existing.txt"
        target.write_text("original")
        step = WriteFileStep(
            id="write-over",
            path=str(target),
            content="updated",
        )
        result = step.run({})
        assert result.status == "ok"
        assert target.read_text() == "updated"

    def test_revert_deletes_created_file(self, tmp_path):
        target = tmp_path / "created.txt"
        step = WriteFileStep(
            id="rev-create",
            path=str(target),
            content="data",
        )
        step.run({})
        assert target.exists()
        step.revert({})
        assert not target.exists()

    def test_revert_restores_prior_content(self, tmp_path):
        target = tmp_path / "prior.txt"
        target.write_text("original content")
        step = WriteFileStep(
            id="rev-restore",
            path=str(target),
            content="new content",
        )
        step.run({})
        assert target.read_text() == "new content"
        step.revert({})
        assert target.read_text() == "original content"

    def test_revert_before_run_skipped(self, tmp_path):
        step = WriteFileStep(
            id="no-run-write",
            path=str(tmp_path / "z.txt"),
            content="c",
        )
        result = step.revert({})
        assert result.status == "skipped"

    def test_dry_run(self, tmp_path):
        target = tmp_path / "dry.txt"
        step = WriteFileStep(
            id="dry-write",
            path=str(target),
            content="c",
        )
        result = step.dry_run({})
        assert result.status == "planned"
        assert not target.exists()

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "file.txt"
        step = WriteFileStep(
            id="parents",
            path=str(target),
            content="data",
            create_parents=True,
        )
        result = step.run({})
        assert result.status == "ok"
        assert target.exists()

    def test_registry_integration(self, tmp_path):
        registry = MagicMock()
        target = tmp_path / "reg.txt"
        step = WriteFileStep(
            id="reg-write",
            path=str(target),
            content="data",
            registry=registry,
            recipe_id="test-recipe",
        )
        step.run({})
        assert registry.register.called
        call_kwargs = registry.register.call_args[1]
        assert "files" in call_kwargs


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestProvisionStepFromDict:
    def test_shell_step(self):
        step = provision_step_from_dict(
            {"type": "shell", "id": "s1", "command": ["echo", "hi"]},
            {},
        )
        assert isinstance(step, ShellProvisionStep)
        assert step.id == "s1"

    def test_shell_step_substitutes_backend_params_at_factory_time(self):
        step = provision_step_from_dict(
            {
                "type": "shell",
                "id": "install",
                "command": ["hindsight-cline", "install", "--api-url={URL}", "--api-token={KEY}"],
                "revert_command": ["hindsight-cline", "uninstall", "--api-token={KEY}"],
            },
            {"URL": "https://hs.example.com", "KEY": "sk-test"},
        )

        assert isinstance(step, ShellProvisionStep)
        assert step.command == [
            "hindsight-cline",
            "install",
            "--api-url=https://hs.example.com",
            "--api-token=sk-test",
        ]
        assert step.revert_command == [
            "hindsight-cline",
            "uninstall",
            "--api-token=sk-test",
        ]

    def test_shell_step_unknown_placeholder_raises_at_factory_time(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            provision_step_from_dict(
                {"type": "shell", "id": "bad", "command": ["tool", "--url={URL}"]},
                {},
            )
        assert exc_info.value.code == "VAL-PSTEP-002"

    def test_config_set_step(self):
        step = provision_step_from_dict(
            {"type": "config-set", "id": "c1", "path": "/tmp/x.json", "key_path": ("a", "b"), "value": "{VAL}"},
            {"VAL": "42"},
        )
        assert isinstance(step, ConfigSetStep)

    def test_managed_block_step(self):
        step = provision_step_from_dict(
            {"type": "managed-block", "id": "m1", "path": "/tmp/f.txt", "block_id": "b1", "content": "{TXT}"},
            {"TXT": "hello"},
        )
        assert isinstance(step, ManagedBlockStep)

    def test_write_file_step(self):
        step = provision_step_from_dict(
            {"type": "write-file", "id": "w1", "path": "/tmp/out.txt", "content": "{BODY}"},
            {"BODY": "world"},
        )
        assert isinstance(step, WriteFileStep)

    def test_unknown_type_raises(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            provision_step_from_dict({"type": "unknown", "id": "x"}, {})
        assert exc_info.value.code == "VAL-PSTEP-001"

    def test_missing_type_raises(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            provision_step_from_dict({"id": "x"}, {})
        assert exc_info.value.code == "VAL-PSTEP-001"

    def test_key_path_string_split(self):
        step = provision_step_from_dict(
            {"type": "config-set", "path": "/tmp/x.json", "key_path": "a.b.c", "value": "v"},
            {},
        )
        assert isinstance(step, ConfigSetStep)
        assert step.key_path == ("a", "b", "c")

    def test_anonymous_id(self):
        step = provision_step_from_dict(
            {"type": "shell", "command": ["echo"]},
            {},
        )
        assert step.id == "shell-anonymous"

    def test_config_set_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.chdir(cwd)

        step = ConfigSetStep(
            id="home-config",
            path="~/cfg.json",
            key_path=("server", "url"),
            value="https://hs.example.com",
        )
        result = step.run({})

        assert result.status == "ok"
        assert json.loads((home / "cfg.json").read_text())["server"]["url"] == "https://hs.example.com"
        assert not (cwd / "~").exists()

    def test_write_file_expands_user_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        cwd = tmp_path / "cwd"
        home.mkdir()
        cwd.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.chdir(cwd)

        step = WriteFileStep(id="home-file", path="~/out.txt", content="hello")
        result = step.run({})

        assert result.status == "ok"
        assert (home / "out.txt").read_text() == "hello"
        assert not (cwd / "~").exists()


# ---------------------------------------------------------------------------
# No component imports (S1 layering)
# ---------------------------------------------------------------------------


class TestLayering:
    def test_no_component_imports(self):
        import ast
        from pathlib import Path

        from audiagentic.foundation.toolchains import provision_steps as ps_pkg

        pkg_dir = Path(ps_pkg.__file__).parent  # type: ignore[attr-defined]
        for source in pkg_dir.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("audiagentic.components"), (
                        f"{source.name} must not import from components/: {node.module}"
                    )


class TestStepTypeRegistry:
    def test_custom_step_type_registers_without_foundation_edits(self):
        """A consumer can register a new step kind and round-trip it through the factory."""
        from audiagentic.foundation.toolchains.provision_steps import (
            provision_step_from_dict,
            register_step_type,
        )
        from audiagentic.foundation.toolchains.provision_steps.base import _STEP_TYPES

        class DummyStep:
            def __init__(self, id: str, note: str) -> None:
                self.id = id
                self.note = note

            def run(self, context):  # pragma: no cover - not exercised
                raise NotImplementedError

            def revert(self, context):  # pragma: no cover
                raise NotImplementedError

            def dry_run(self, context):  # pragma: no cover
                raise NotImplementedError

        def _dummy_from_dict(data, params, registry, recipe_id):
            return DummyStep(id=data.get("id", "dummy"), note=data.get("note", ""))

        register_step_type("dummy-step", _dummy_from_dict)
        try:
            step = provision_step_from_dict({"type": "dummy-step", "id": "d1", "note": "hi"}, {})
            assert isinstance(step, DummyStep)
            assert step.id == "d1"
            assert step.note == "hi"
        finally:
            _STEP_TYPES.pop("dummy-step", None)


# ---------------------------------------------------------------------------
# RS13 - Characterization: substitution and path behavior
# ---------------------------------------------------------------------------


class TestSubstituteStrictAtDefinitionTime:
    """RS13a: _substitute() is strict at YAML-parse (definition) time."""

    def test_substitute_is_strict_at_definition_time(self):
        """Unknown placeholder raises VAL-PSTEP-002 at parse time, not run time."""
        with pytest.raises(AudiaGenticError) as exc_info:
            _substitute("{UNKNOWN_PLACEHOLDER}", {"OTHER": "val"}, "definition")
        assert exc_info.value.code == "VAL-PSTEP-002"


class TestSubstituteParamsLenient:
    """RS13b: substitute_params() leaves unknown/unset placeholders literal."""

    def test_substitute_params_is_lenient(self):
        from audiagentic.foundation.toolchains.provision_steps.factory import (
            substitute_params,
        )

        result = substitute_params("--url={UNKNOWN}", {})
        assert result == "--url={UNKNOWN}"


class TestShellStepTwoSubstitutionPasses:
    """RS13c: ShellProvisionStep applies two substitution passes."""

    def test_shell_step_two_substitution_passes_intentional(self):
        """First pass at factory (_substitute for {PARAM}), second at run (str.format for {context_key}).

        Pass GREETING as a known param and name as literal "{name}" so the factory
        resolves GREETING but preserves the runtime placeholder. Then _render applies
        str.format with context, substituting name=Alice.
        """
        step = provision_step_from_dict(
            {
                "type": "shell",
                "id": "two-pass",
                "command": "echo {GREETING} {name}",
                "shell": True,
            },
            {"GREETING": "hello", "name": "{name}"},
        )

        assert isinstance(step, ShellProvisionStep)
        assert step.command == "echo hello {name}"

        result = step.run({"name": "Alice"})
        assert result.status == "ok"


class TestFoundationPathNoProjectRootAnchoring:
    """RS13d: Foundation path steps have NO concept of project root."""

    def test_foundation_path_no_project_root_anchoring(self):
        home = Path.home()
        step = WriteFileStep(
            id="home-path",
            path="~/some/path/file.txt",
            content="data",
            create_parents=True,
        )
        result = step.run({})
        assert result.status == "ok"
        expected = home / "some" / "path" / "file.txt"
        assert expected.exists()
        assert expected.read_text() == "data"


class TestHindsightAbsoluteProjectPathAnchors:
    """RS13e: _absolute_project_path anchors relative paths against project_root."""

    def test_hindsight_absolute_project_path_anchors(self):
        from audiagentic.components.memory.hindsight.recipes import (
            _absolute_project_path,
        )

        result = _absolute_project_path("subdir/file.txt", Path("/project"))
        assert result == Path("/project/subdir/file.txt")

    def test_hindsight_absolute_project_path_ignores_root_for_absolute(self):
        from audiagentic.components.memory.hindsight.recipes import (
            _absolute_project_path,
        )

        result = _absolute_project_path("/etc/config", Path("/project"))
        assert result == Path("/etc/config")

    def test_hindsight_absolute_project_path_expands_user(self):
        from audiagentic.components.memory.hindsight.recipes import (
            _absolute_project_path,
        )

        result = _absolute_project_path("~/file.txt", Path("/project"))
        assert result == Path.home() / "file.txt"
