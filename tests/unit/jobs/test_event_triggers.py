"""Tests for event-trigger configuration loader (EDJ01)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audiagentic.components.agent_jobs.event_triggers import load_event_triggers
from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
)
from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    get_error_resolution,
)


@pytest.fixture(autouse=True, scope="session")
def _load_error_resolutions() -> None:
    config_dirs = [
        Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    ]
    load_all_error_resolutions(config_dirs)


def _write_config(project_root: Path, triggers: list[dict]) -> None:
    config_dir = project_root / ".audiagentic" / "config" / "agent-jobs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "event-triggers.yaml"
    config_path.write_text(
        yaml.safe_dump({"triggers": triggers}),
        encoding="utf-8",
    )


def _valid_trigger(overrides: dict | None = None) -> dict:
    base = {
        "contract-version": "v1",
        "trigger-id": "test-trigger",
        "kind": "event",
        "event-pattern": "planning.item.created",
        "prompt-template": "Review {{subject}}.",
    }
    if overrides:
        base.update(overrides)
    return base


class TestLoadValidTriggers:
    def test_single_valid_trigger_loads(self, tmp_path: Path) -> None:
        _write_config(tmp_path, [_valid_trigger()])

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        t = triggers[0]
        assert t.trigger_id == "test-trigger"
        assert t.kind == "event"
        assert t.event_pattern == "planning.item.created"
        assert t.prompt_template == "Review {{subject}}."

    def test_multiple_valid_triggers_load(self, tmp_path: Path) -> None:
        # Create the template file that t3 references
        tmpl_dir = tmp_path / ".audiagentic" / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "review.md").write_text("This is a review template.\n", encoding="utf-8")

        t3 = _valid_trigger(
            {
                "trigger-id": "t3",
                "event-pattern": "planning.**",
            }
        )
        del t3["prompt-template"]
        t3["prompt-template-file"] = ".audiagentic/prompts/review.md"

        _write_config(
            tmp_path,
            [
                _valid_trigger({"trigger-id": "t1", "event-pattern": "planning.item.created"}),
                _valid_trigger({"trigger-id": "t2", "event-pattern": "planning.item.*"}),
                t3,
            ],
        )

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 3
        ids = [t.trigger_id for t in triggers]
        assert ids == ["t1", "t2", "t3"]
        # t3's template was loaded from file at registration time
        pt = triggers[2].prompt_template
        assert pt is not None and "review template" in pt

    def test_prompt_template_file_variant(self, tmp_path: Path) -> None:
        # Create the template file
        tmpl_dir = tmp_path / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "review.md").write_text("File-based template content.\n", encoding="utf-8")

        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = "prompts/review.md"
        _write_config(tmp_path, [trigger])

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        assert triggers[0].prompt_template_file == "prompts/review.md"
        # Template content loaded from file at registration time
        pt = triggers[0].prompt_template
        assert pt is not None and "File-based template" in pt

    def test_optional_fields_round_trip(self, tmp_path: Path) -> None:
        trigger = _valid_trigger(
            {
                "agent-profile-id": "codex-default",
                "workflow-profile": "strict",
                "target": {"kind": "adhoc", "adhoc-id": "adhoc-1"},
                "metadata-propagation": {"correlation_id": True},
            }
        )
        _write_config(tmp_path, [trigger])

        triggers = load_event_triggers(tmp_path)
        t = triggers[0]
        assert t.agent_profile_id == "codex-default"
        assert t.workflow_profile == "strict"
        assert t.target == {"kind": "adhoc", "adhoc-id": "adhoc-1"}
        assert t.metadata_propagation == {"correlation_id": True}

    def test_no_config_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_event_triggers(tmp_path) == []


class TestDisabledTriggers:
    def test_disabled_trigger_skipped(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            [
                _valid_trigger({"trigger-id": "enabled-t", "enabled": True}),
                _valid_trigger({"trigger-id": "disabled-t", "enabled": False}),
            ],
        )

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        assert triggers[0].trigger_id == "enabled-t"

    def test_all_disabled_returns_empty(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            [_valid_trigger({"enabled": False})],
        )
        assert load_event_triggers(tmp_path) == []


class TestMissingRequiredFields:
    def test_missing_trigger_id_raises_VAL_AJT_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["trigger-id"]
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"
        assert get_error_resolution("VAL-AJT-001") is not None

    def test_missing_kind_raises_VAL_AJT_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["kind"]
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"

    def test_missing_contract_version_raises_VAL_AJT_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["contract-version"]
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"

    def test_missing_event_pattern_for_event_kind(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["event-pattern"]
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"


class TestUnknownFields:
    def test_unknown_field_mode_rejected(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        trigger["mode"] = "blocking"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"

    def test_unknown_field_random_rejected(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        trigger["some-random-field"] = "value"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-001"


class TestDuplicateTriggerId:
    def test_duplicate_trigger_id_raises_VAL_AJT_002(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            [
                _valid_trigger({"trigger-id": "dup"}),
                _valid_trigger({"trigger-id": "dup"}),
            ],
        )

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-002"
        assert get_error_resolution("VAL-AJT-002") is not None


class TestTemplateXOR:
    def test_both_templates_raises_VAL_AJT_003(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        trigger["prompt-template-file"] = "prompts/other.md"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-003"
        assert get_error_resolution("VAL-AJT-003") is not None

    def test_neither_template_raises_VAL_AJT_003(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["prompt-template"]
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-003"


class TestErrorResolutionsRegistered:
    def test_all_error_codes_have_resolutions(self) -> None:
        for code in ("VAL-AJT-001", "VAL-AJT-002", "VAL-AJT-003",
                      "IO-PTMPL-001", "IO-PTMPL-002"):
            resolution = get_error_resolution(code)
            assert resolution is not None, f"Missing error resolution for {code}"
            assert isinstance(resolution, str)
            assert len(resolution) > 0


class TestFileTemplateLoading:
    """EDJ11 — load prompt templates from file at registration time."""

    def test_load_relative_path(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / ".audiagentic" / "prompts" / "jobs" / "events"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "onboard.md").write_text(
            "Onboard {subject}.\n", encoding="utf-8"
        )

        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = ".audiagentic/prompts/jobs/events/onboard.md"
        _write_config(tmp_path, [trigger])

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        pt = triggers[0].prompt_template
        assert pt is not None and "Onboard" in pt

    def test_load_absolute_path_within_root(self, tmp_path: Path) -> None:
        tmpl_dir = tmp_path / ".audiagentic" / "prompts" / "jobs"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        abs_file = tmpl_dir / "review.md"
        abs_file.write_text("Absolute path template.\n", encoding="utf-8")

        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = str(abs_file)
        _write_config(tmp_path, [trigger])

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        pt = triggers[0].prompt_template
        assert pt is not None and "Absolute path" in pt

    def test_load_symlink_within_root(self, tmp_path: Path) -> None:
        # Create actual template file
        tmpl_dir = tmp_path / ".audiagentic" / "prompts"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        real_file = tmpl_dir / "real.md"
        real_file.write_text("Symlink target content.\n", encoding="utf-8")

        # Create symlink pointing to the same file (may fail without privileges on Windows)
        link_file = tmpl_dir / "linked.md"
        try:
            link_file.symlink_to(real_file)
        except OSError:
            pytest.skip("symlink creation requires elevated privileges")

        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = str(link_file)
        _write_config(tmp_path, [trigger])

        triggers = load_event_triggers(tmp_path)
        assert len(triggers) == 1
        pt = triggers[0].prompt_template
        assert pt is not None and "Symlink target" in pt

    def test_missing_file_raises_IO_PTMPL_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = ".audiagentic/prompts/nonexistent.md"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "IO-PTMPL-001"

    def test_path_escape_raises_IO_PATH_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = "../../../etc/passwd"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "IO-PATH-001"

    def test_absolute_path_escape_raises_IO_PATH_001(self, tmp_path: Path) -> None:
        trigger = _valid_trigger()
        del trigger["prompt-template"]
        trigger["prompt-template-file"] = "/etc/shadow"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "IO-PATH-001"

    def test_template_content_replaces_inline(self, tmp_path: Path) -> None:
        # When both inline and file exist (shouldn't happen due to XOR),
        # inline is preferred.  Verify by checking the XOR guard still fires.
        trigger = _valid_trigger()
        trigger["prompt-template-file"] = ".audiagentic/prompts/extra.md"
        _write_config(tmp_path, [trigger])

        with pytest.raises(AudiaGenticError) as exc_info:
            load_event_triggers(tmp_path)
        assert exc_info.value.code == "VAL-AJT-003"
