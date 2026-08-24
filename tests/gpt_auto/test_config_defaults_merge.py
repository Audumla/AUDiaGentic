"""GP20: gpt-auto's three-tier-ready config loader (packaged defaults +
project overlay). Covers deep_merge()'s recursive/replace semantics and
GptAutoConfig.from_project_dict()'s resolution against defaults.yaml."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.gpt_auto.config import (
    CURRENT_CONTRACT_VERSION,
    GptAutoConfig,
    deep_merge,
    machine_gpt_auto_override_path,
    validate_machine_gpt_auto_config,
    validate_project_gpt_auto_config,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_greenfield_config_urls import valid_config


def test_deep_merge_recurses_into_nested_dicts_without_dropping_siblings() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 20}}

    merged = deep_merge(base, override)

    assert merged == {"a": 1, "nested": {"x": 1, "y": 20}}


def test_deep_merge_replaces_lists_wholesale_not_concatenates() -> None:
    base = {"selectors": ["a", "b"]}
    override = {"selectors": ["c"]}

    merged = deep_merge(base, override)

    assert merged == {"selectors": ["c"]}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"nested": {"x": 1}}
    override = {"nested": {"x": 2}}

    deep_merge(base, override)

    assert base == {"nested": {"x": 1}}
    assert override == {"nested": {"x": 2}}


def test_from_project_dict_resolves_a_sparse_overlay_specifying_only_project_url() -> None:
    """The core GP20 acceptance criterion: a project overlay specifying only
    project-url (plus the still-required contract-version) resolves to a
    complete, valid GptAutoConfig via packaged defaults."""
    overlay = {
        "settings": {
            "contract-version": "v1",
            "project-url": "https://chatgpt.com/g/g-p-test-project",
        }
    }

    config = GptAutoConfig.from_project_dict(overlay)

    assert config.project_url == "https://chatgpt.com/g/g-p-test-project"
    # Values not mentioned in the overlay come from defaults.yaml.
    assert config.browser.remote_debugging_port == 9222
    assert config.turn.response_timeout_seconds == 3600
    assert config.workflow.policy("response-complete").all_of


def test_from_project_dict_tolerates_an_already_unwrapped_settings_dict() -> None:
    """Real live bug, 2026-08-17: some callers (the live stress test
    harness's _load_live_settings(), which does data.get('settings', data)
    itself before passing the result on) pass an already-unwrapped bare
    settings dict, not the {"settings": {...}} shape every on-disk config
    file has. Merging a wrapped defaults.yaml against an unwrapped project
    dict without unwrapping both first silently discards every project
    override (project-url included) and falls through to defaults."""
    unwrapped_overlay = {
        "contract-version": "v1",
        "project-url": "https://chatgpt.com/g/g-p-unwrapped-test",
    }

    config = GptAutoConfig.from_project_dict(unwrapped_overlay)

    assert config.project_url == "https://chatgpt.com/g/g-p-unwrapped-test"
    assert config.browser.remote_debugging_port == 9222


def test_from_project_dict_overlay_override_wins_over_defaults() -> None:
    overlay = {
        "settings": {
            "contract-version": "v1",
            "project-url": "https://chatgpt.com/g/g-p-test-project",
            "turn": {"response-timeout-seconds": 60},
        }
    }

    config = GptAutoConfig.from_project_dict(overlay)

    assert config.turn.response_timeout_seconds == 60
    # Sibling turn fields not overridden still come from defaults.
    assert config.turn.poll_interval_seconds == 1


def test_v1_config_missing_gp07_fields_migrates_with_sane_defaults() -> None:
    """GP21: a v1 project config predating GP07's two new required
    submission-proof fields must not hard-fail the whole shared gateway --
    the exact bigcherry incident GP09 was raised about. Migration fills
    v1-era defaults instead."""
    data = copy.deepcopy(valid_config())
    del data["turn"]["submission-proof-progress-lease-seconds"]
    del data["turn"]["submission-proof-absolute-ceiling-seconds"]

    config = GptAutoConfig.from_dict(data)

    assert config.turn.submission_proof_progress_lease_seconds == 300
    assert config.turn.submission_proof_absolute_ceiling_seconds == 900
    # The resolved config always reports the current schema version, not
    # whatever version the input declared.
    assert config.contract_version == CURRENT_CONTRACT_VERSION


def test_v1_config_that_already_sets_gp07_fields_keeps_its_own_values() -> None:
    """Migration only fills genuinely missing keys -- an explicit v1 config
    that already sets these (unusual but not invalid) is not silently
    overridden."""
    data = copy.deepcopy(valid_config())
    data["turn"]["submission-proof-progress-lease-seconds"] = 42
    data["turn"]["submission-proof-absolute-ceiling-seconds"] = 99

    config = GptAutoConfig.from_dict(data)

    assert config.turn.submission_proof_progress_lease_seconds == 42
    assert config.turn.submission_proof_absolute_ceiling_seconds == 99


def test_v2_contract_version_accepted_directly_without_migration() -> None:
    data = copy.deepcopy(valid_config())
    data["contract-version"] = "v2"

    config = GptAutoConfig.from_dict(data)

    assert config.contract_version == CURRENT_CONTRACT_VERSION


def test_unsupported_contract_version_is_rejected_clearly() -> None:
    data = copy.deepcopy(valid_config())
    data["contract-version"] = "v3"

    with pytest.raises(AudiaGenticError) as exc_info:
        GptAutoConfig.from_dict(data)

    assert exc_info.value.code == "VAL-GPTAUTO-001"


# ── GP26: machine-level config validation entry points ──────────────────────


def test_machine_override_path_respects_audiagentic_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", "C:/tmp/audihome")

    path = machine_gpt_auto_override_path("gpt-auto")

    assert path == Path("C:/tmp/audihome/config/providers/gpt-auto.yaml")


def test_validate_machine_config_succeeds_with_defaults_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", "C:/tmp/empty-audihome")

    validate_machine_gpt_auto_config()


def test_validate_machine_config_applies_machine_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path))
    provider_dir = tmp_path / "config" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "gpt-auto.yaml").write_text(
        "settings:\n  contract-version: v1\n  turn:\n    response-timeout-seconds: 42\n",
        encoding="utf-8",
    )

    validate_machine_gpt_auto_config()

    resolved = validate_project_gpt_auto_config(tmp_path / "some-project")
    assert resolved.turn.response_timeout_seconds == 42


def test_validate_machine_config_rejects_invalid_machine_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GP26: an invalid MACHINE-level config is startup-fatal."""
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path))
    provider_dir = tmp_path / "config" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "gpt-auto.yaml").write_text(
        "settings:\n  contract-version: v99\n  turn:\n    response-timeout-seconds: 42\n",
        encoding="utf-8",
    )

    with pytest.raises(AudiaGenticError) as exc_info:
        validate_machine_gpt_auto_config()

    assert exc_info.value.code == "VAL-GPTAUTO-001"


def test_validate_project_config_returns_effective_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "audihome"))
    project = tmp_path / "project"
    provider_dir = project / ".audiagentic" / "config" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "gpt-auto.yaml").write_text(
        "settings:\n"
        "  contract-version: v1\n"
        "  project-url: https://chatgpt.com/g/g-p-test-project\n",
        encoding="utf-8",
    )

    config = validate_project_gpt_auto_config(project)

    assert config.project_url == "https://chatgpt.com/g/g-p-test-project"
    assert config.turn.response_timeout_seconds == 3600


def test_validate_project_config_without_settings_resolves_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "audihome"))
    config = validate_project_gpt_auto_config(tmp_path)

    assert config.turn.response_timeout_seconds == 3600


def test_metadata_only_project_provider_file_resolves_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider descriptor metadata must not be parsed as runtime settings.

    Other projects commonly carry an install/access declaration without a
    gpt-auto ``settings`` block.  That is a valid sparse overlay and must use
    the packaged defaults rather than fail with VAL-GPTAUTO-001.
    """
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "audihome"))
    provider_dir = tmp_path / "project" / ".audiagentic" / "config" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "gpt-auto.yaml").write_text(
        "install-mode: external-configured\naccess-mode: none\n",
        encoding="utf-8",
    )

    config = validate_project_gpt_auto_config(provider_dir.parents[2])

    assert config.project_url is None
    assert config.turn.response_timeout_seconds == 3600


def test_validate_project_config_rejects_incompatible_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GP26: an invalid PROJECT config must be isolated to that project."""
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "audihome"))
    project = tmp_path / "project"
    provider_dir = project / ".audiagentic" / "config" / "providers"
    provider_dir.mkdir(parents=True)
    (provider_dir / "gpt-auto.yaml").write_text(
        "settings:\n  contract-version: v1\n  browser:\n    executable: 42\n",
        encoding="utf-8",
    )

    with pytest.raises(AudiaGenticError) as exc_info:
        validate_project_gpt_auto_config(project)

    assert exc_info.value.code == "VAL-GPTAUTO-001"

