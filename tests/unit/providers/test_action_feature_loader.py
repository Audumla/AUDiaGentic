from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.providers.tags import registry
from audiagentic.components.optional.providers.tags.loader import (
    _load_tags_from_component_config,
    load_action_feature_from_yaml,
    load_tag_from_yaml,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features import registry as feature_registry


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _action_yaml(*, descriptor_type: str) -> str:
    if descriptor_type == "feature":
        header = "\n".join([
            "type: feature",
            "parent: agent-jobs",
            "kind: action",
        ])
    else:
        header = "type: action"
    return "\n".join([
        header,
        "contract-version: v1",
        "id: ag-test/doctrine",
        "title: Test action doctrine",
        "content:",
        "  body: |",
        "    Test primary instruction.",
        "tag-id: ag-test",
        "display-name: Test",
        "description: Test action",
        "aliases:",
        "  - agt",
        "directives:",
        "  - id",
        "  - target",
        "requires-body: false",
        "is-generic-tag: false",
        "is-review-tag: true",
        "skill-content-file: ag-test-skill.md",
        "instructions:",
        "  - id: ag-test/extra",
        "    title: Extra policy",
        "    content:",
        "      body: Extra instruction.",
        "prompts:",
        "  - name: default",
        "    content-file: ag-test-prompt-default.md",
    ])


def _projection_tuple(descriptor) -> tuple:
    return (
        descriptor.tag_id,
        descriptor.display_name,
        descriptor.description,
        descriptor.skill_content_file,
        descriptor.aliases,
        descriptor.directives,
        descriptor.requires_body,
        descriptor.is_generic_tag,
        descriptor.is_review_tag,
        tuple((i.contribution_id, i.title, i.body.strip(), i.preferred_targets) for i in descriptor.instructions),
        tuple((p.name, p.content_file) for p in descriptor.prompts),
        descriptor.owner_component_id,
    )


def setup_function() -> None:
    registry._registry.clear()
    registry._loaded = False
    feature_registry.clear()


def teardown_function() -> None:
    registry._registry.clear()
    registry._loaded = False
    feature_registry.clear()


def test_action_feature_projects_to_action_descriptor(tmp_path: Path) -> None:
    feature_path = _write(tmp_path / "feature.yaml", _action_yaml(descriptor_type="feature"))

    feature = load_action_feature_from_yaml(feature_path, owner_component_id="agent-jobs")

    assert _projection_tuple(feature) == (
        "ag-test",
        "Test",
        "Test action",
        "ag-test-skill.md",
        ("agt",),
        ("id", "target"),
        False,
        False,
        True,
        (
            ("ag-test/doctrine", "Test action doctrine", "Test primary instruction.", ()),
            ("ag-test/extra", "Extra policy", "Extra instruction.", ()),
        ),
        (("default", "ag-test-prompt-default.md"),),
        "agent-jobs",
    )
    assert feature_registry.get_feature("agent-jobs", "action", "ag-test/doctrine") is not None
    assert registry.get_tag("ag-test") == feature


def test_legacy_action_descriptor_type_is_rejected(tmp_path: Path) -> None:
    legacy_path = _write(tmp_path / "legacy.yaml", _action_yaml(descriptor_type="action"))

    try:
        load_tag_from_yaml(legacy_path, owner_component_id="agent-jobs")
    except AudiaGenticError as exc:
        assert exc.code == "VAL-PTAG-003"
        assert exc.kind == "providers"
        assert exc.details["expected"] == "feature"
        assert exc.details["actual"] == "action"
    else:
        raise AssertionError("legacy type=action descriptor should be rejected")


def test_component_config_can_reference_action_feature(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    _write(
        config_root / "components" / "optional" / "agent-jobs.yaml",
        """
type: component
id: agent-jobs
contributions:
  - config: components/optional/agent-jobs/ag-test.yaml
""".strip(),
    )
    _write(
        config_root / "components" / "optional" / "agent-jobs" / "ag-test.yaml",
        _action_yaml(descriptor_type="feature"),
    )

    descriptors = _load_tags_from_component_config(
        config_root / "components" / "optional" / "agent-jobs.yaml",
        config_root,
        owner_component_id="agent-jobs",
    )

    assert [descriptor.tag_id for descriptor in descriptors] == ["ag-test"]
    assert descriptors[0].owner_component_id == "agent-jobs"
    assert feature_registry.get_feature("agent-jobs", "action", "ag-test/doctrine") is not None
