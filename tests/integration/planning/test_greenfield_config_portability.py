from __future__ import annotations

import json
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.config import Config
from audiagentic.planning.fs.read import parse_markdown
from audiagentic.planning.fs.write import dump_markdown


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def _seed_greenfield_project(root: Path) -> None:
    config_dir = root / ".audiagentic" / "planning" / "config"
    for sub in ("meta", "indexes", "events", "claims", "extracts", "cache"):
        (root / ".audiagentic" / "planning" / sub).mkdir(parents=True, exist_ok=True)
    (root / ".audiagentic" / "planning" / "indexes" / "lookup.json").write_text(
        "{}",
        encoding="utf-8",
    )

    _write(
        config_dir / "planning.yaml",
        """
        planning:
          default_profile: atelier
          default_guidance: spark
          conventions:
            ref_field_suffixes:
              _ref: scalar_ref
              _refs: scalar_ref_list
          naming:
            numeric_format: preserve_id
            slug_policy: always
            default_pattern: "{id}-{slug}.md"
          kind_aliases:
            ping: signal
            board: sketch
            step: action
          kinds:
            signal:
              dir: intake
              id_prefix: signal
              counter_file: signals.json
              has_domain: false
              required_refs: []
              reference_inheritance: {}
              creation:
                duplicate_check: true
                require_source: true
                extra_fields:
                  source_field: origin
              required_fields: [id, label, state, summary]
              optional_fields: [origin, standard_refs]
            sketch:
              dir: sketches
              id_prefix: sketch
              counter_file: sketches.json
              has_domain: false
              required_refs: []
              creation:
                extra_fields:
                  guidance_field: guidance
              reference_inheritance: {}
              required_fields: [id, label, state, summary]
              optional_fields: [guidance, signal_refs, standard_refs]
            action:
              dir: moves
              id_prefix: action
              counter_file: actions.json
              has_domain: true
              required_refs: []
              reference_inheritance:
                standard_refs:
                  - field: sketch_ref
                    type: direct
              required_fields: [id, label, state, summary]
              optional_fields: [sketch_ref, sketch_refs, standard_refs]
          reference_field_shapes:
            sketch_refs: rel_list
          default_reference_field: standard_refs
          lifecycle:
            state_set_priority:
              initial: 10
              active: 20
              complete: 90
              terminal: 100
            state_sets:
              signal:
                channel:
                  initial: [inbox]
                  active: [triaged]
                  complete: [filed]
                  terminal: [frozen]
              sketch:
                studio:
                  initial: [shaping]
                  complete: [approved]
                  terminal: [retired]
              action:
                runway:
                  initial: [queued]
                  active: [active]
                  terminal: [retired]
            actions:
              freeze:
                transition_to: frozen
                cascade:
                  by_kind:
                    signal:
                      sketch: retired
              retire:
                transition_to: retired
                cascade:
                  by_kind:
                    sketch:
                      action: retired
          dirs:
            base: records/atlas
            attachments: records/assets
            indexes: .audiagentic/planning/indexes
            meta: .audiagentic/planning/meta
            extracts: .audiagentic/planning/extracts
            events: .audiagentic/planning/events
            claims: .audiagentic/planning/claims
            cache: .audiagentic/planning/cache
          base_required_fields: [id, label, state, summary]
          base_optional_fields: [meta]
          soft_delete:
            flag_field: deleted
            timestamp_field: deleted_at
            reason_field: deletion_reason
        """,
    )
    _write(
        config_dir / "profiles.yaml",
        """
        planning:
          guidance_levels:
            spark:
              description: Fast spark pass
              label: Spark
              defaults: {}
            forge:
              description: Deep forge pass
              label: Forge
              defaults: {}
              sections_by_kind:
                sketch:
                  required: [Concept, Edges, Pressure]
          profiles:
            atelier:
              description: Greenfield creative flow
              label: Atelier
              on_create: []
              defaults: {}
              suggested_sections: []
          document_templates:
            signal:
              default: "# Signal\\n\\n\\n# Framing\\n"
              by_guidance:
                spark: "# Signal\\n\\n\\n# Framing\\n"
                forge: "# Signal\\n\\n\\n# Framing\\n\\n\\n# Pressure\\n"
          relationship_config:
            signal:
              can_reference: [sketch]
              required_for_children: []
              referenced_by:
                sketch: signal_refs
              requires_children:
                sketch:
                  states: [filed]
            sketch:
              can_reference: [signal, action]
              required_for_children: []
              referenced_by:
                action: sketch_ref
              requires_children:
                action:
                  states: [approved]
            action:
              can_reference: [sketch]
              required_for_children: []
          required_sections: {}
          state_section_requirements: {}
        """,
    )
    _write(
        config_dir / "workflows.yaml",
        """
        planning:
          workflows:
            signal:
              default: channel
              named:
                channel:
                  initial: inbox
                  values: [inbox, triaged, filed, frozen]
                  transitions:
                    inbox: [triaged, frozen]
                    triaged: [filed, frozen]
                    filed: [frozen]
                    frozen: []
            sketch:
              default: studio
              named:
                studio:
                  initial: shaping
                  values: [shaping, approved, retired]
                  transitions:
                    shaping: [approved, retired]
                    approved: [retired]
                    retired: []
            action:
              default: runway
              named:
                runway:
                  initial: queued
                  values: [queued, active, retired]
                  transitions:
                    queued: [active, retired]
                    active: [retired]
                    retired: []
        """,
    )
    _write(
        config_dir / "automations.yaml",
        """
        planning:
          automations: []
        """,
    )

    _write(config_dir / "templates" / "signal" / "default.md", "# Signal\n\n\n# Framing\n")
    _write(config_dir / "templates" / "sketch" / "default.md", "# Concept\n\n\n# Edges\n")
    _write(
        config_dir / "templates" / "sketch" / "forge.md",
        "# Concept\n\n\n# Edges\n\n\n# Pressure\n",
    )
    _write(config_dir / "templates" / "action" / "default.md", "# Mission\n\n\n# Exit Checks\n")


def test_greenfield_config_supports_custom_kinds_workflows_templates_and_refs(tmp_path: Path) -> None:
    _seed_greenfield_project(tmp_path)
    cfg = Config(tmp_path)
    assert cfg.validate() == []
    assert cfg.default_guidance() == "spark"
    assert set(cfg.guidance_levels()) == {"spark", "forge"}
    assert cfg.guidance_required_sections("forge", "sketch") == ["Concept", "Edges", "Pressure"]

    api = PlanningAPI(tmp_path)

    signal = api.new(
        "ping",
        label="Market pulse",
        summary="Capture weak signal",
        source="brief-001",
    )
    sketch = api.new(
        "board",
        label="Shape route",
        summary="Explore design edges",
        guidance="forge",
    )
    action = api.new("step", label="Pilot slice", summary="Run first move", domain="lab")

    api.relink(sketch.data["id"], "signal_refs", signal.data["id"])
    api.relink(action.data["id"], "sketch_ref", sketch.data["id"])
    api.relink(action.data["id"], "sketch_refs", sketch.data["id"], seq=10, display="lead")

    sketch_with_refs = api.lookup(sketch.data["id"])
    sketch_data, _ = parse_markdown(sketch_with_refs.path)
    sketch_data["standard_refs"] = ["playbook-1"]
    dump_markdown(sketch_with_refs.path, sketch_data, sketch_with_refs.body)
    api.index()

    assert signal.kind == "signal"
    assert sketch.kind == "sketch"
    assert action.kind == "action"
    assert signal.data["state"] == "inbox"
    assert sketch.data["state"] == "shaping"
    assert action.data["state"] == "queued"

    assert signal.path == tmp_path / "records" / "atlas" / "intake" / "signal-1-market-pulse.md"
    assert sketch.path == tmp_path / "records" / "atlas" / "sketches" / "sketch-1-shape-route.md"
    assert action.path == tmp_path / "records" / "atlas" / "moves" / "lab" / "action-1-pilot-slice.md"

    assert "# Signal" in signal.body
    assert "# Concept" in sketch.body
    assert "# Mission" in action.body
    assert "# Pressure" in sketch.body
    assert signal.data["origin"] == "brief-001"
    assert sketch.data["guidance"] == "forge"

    head = api.head(action.data["id"])
    shown = api.extracts.show(action.data["id"])
    extracted = api.extracts.extract(action.data["id"], with_related=True)
    assert head["path"] == "records/atlas/moves/lab/action-1-pilot-slice.md"
    assert shown["kind"] == "action"
    assert shown["path"] == "records/atlas/moves/lab/action-1-pilot-slice.md"
    assert extracted["related"]["sketch_ref"] == sketch.data["id"]
    assert extracted["related"]["sketch_refs"] == [
        {"ref": sketch.data["id"], "seq": 10, "display": "lead"}
    ]
    assert extracted["effective_refs"] == ["playbook-1"]

    api.state(signal.data["id"], "triaged")
    api.state(signal.data["id"], "filed")
    api.state(sketch.data["id"], "approved")

    errors = api.validate()
    assert errors == []

    trace = json.loads(
        (tmp_path / ".audiagentic" / "planning" / "indexes" / "trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        ref["src"] == sketch.data["id"]
        and ref["dst"] == signal.data["id"]
        and ref["field"] == "signal_refs"
        for ref in trace["refs"]
    )
    assert any(
        ref["src"] == action.data["id"]
        and ref["dst"] == sketch.data["id"]
        and ref["field"] == "sketch_ref"
        for ref in trace["refs"]
    )
    assert any(
        ref["src"] == action.data["id"]
        and ref["dst"] == sketch.data["id"]
        and ref["field"] == "sketch_refs"
        and ref["seq"] == 10
        and ref["display"] == "lead"
        for ref in trace["refs"]
    )


def test_greenfield_config_cascades_custom_states_between_custom_kinds(tmp_path: Path) -> None:
    _seed_greenfield_project(tmp_path)
    api = PlanningAPI(tmp_path)

    signal = api.new("signal", label="Cold trail", summary="Keep watch", source="watch-1")
    sketch = api.new("sketch", label="Contour", summary="Map options")
    action = api.new("action", label="Probe", summary="Try first probe", domain="lab")

    api.relink(sketch.data["id"], "signal_refs", signal.data["id"])
    api.relink(action.data["id"], "sketch_ref", sketch.data["id"])

    api.state(signal.data["id"], "frozen")

    assert api._find(signal.data["id"]).data["state"] == "frozen"
    assert api._find(sketch.data["id"]).data["state"] == "retired"
    assert api._find(action.data["id"]).data["state"] == "retired"


def test_greenfield_config_supports_custom_replacement_and_ref_validation(
    tmp_path: Path,
) -> None:
    _seed_greenfield_project(tmp_path)
    planning_path = tmp_path / ".audiagentic" / "planning" / "config" / "planning.yaml"
    workflows_path = tmp_path / ".audiagentic" / "planning" / "config" / "workflows.yaml"

    planning = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    planning_cfg = planning["planning"]
    planning_cfg["kinds"]["signal"]["creation"]["refinement_source_prefix"] = "replaces:"
    planning_cfg["kinds"]["signal"]["creation"]["refinement_action"] = "replace"
    planning_cfg["kinds"]["sketch"]["creation"] = {
        "validate_ref_fields": ["signal_refs"],
        "seed_reference_fields": {"signal_refs": "signals"},
    }
    planning_cfg.setdefault("reference_field_targets", {})["signal_refs"] = "signal"
    planning_cfg["lifecycle"]["state_sets"]["signal"]["channel"]["terminal"].append("replaced")
    planning_cfg["lifecycle"]["actions"]["replace"] = {
        "transition_to": "replaced",
        "extensions": {
            "planning_supersede": {
                "superseded_by_field": "replaced_by",
                "supersedes_field": "replaces",
                "reason_template": "Replaced by {new_id}",
                "body_note_template": "\n\n**Replaced by** `{new_id}` on {date}",
                "body_note_section": "# History",
            },
        },
    }
    planning_path.write_text(yaml.safe_dump(planning, sort_keys=False), encoding="utf-8")

    workflows = yaml.safe_load(workflows_path.read_text(encoding="utf-8"))
    channel = workflows["planning"]["workflows"]["signal"]["named"]["channel"]
    channel["values"].append("replaced")
    channel["transitions"]["inbox"].append("replaced")
    channel["transitions"]["triaged"].append("replaced")
    channel["transitions"]["filed"].append("replaced")
    channel["transitions"]["replaced"] = []
    workflows_path.write_text(yaml.safe_dump(workflows, sort_keys=False), encoding="utf-8")

    cfg = Config(tmp_path)
    assert cfg.validate() == []
    api = PlanningAPI(tmp_path)

    old_signal = api.new("signal", label="Old signal", summary="Old", source="brief-old")
    new_signal = api.new(
        "signal",
        label="New signal",
        summary="New",
        source=f"replaces:{old_signal.data['id']}",
    )

    old = api._find(old_signal.data["id"])
    new = api._find(new_signal.data["id"])
    assert old.data["state"] == "replaced"
    assert old.data["meta"]["replaced_by"] == new.data["id"]
    assert new.data["meta"]["replaces"] == old.data["id"]
    assert "# History" in old.body

    sketch = api.new(
        "sketch",
        label="Validated sketch",
        summary="Uses signal",
        refs={"signals": [old.data["id"]]},
    )
    assert sketch.data["signal_refs"] == [old.data["id"]]

    wrong_kind = api.new("action", label="Wrong kind", summary="Not signal", domain="lab")
    with pytest.raises(ValueError, match="expected \\['signal'\\]"):
        api.new(
            "sketch",
            label="Invalid sketch",
            summary="Wrong ref kind",
            refs={"signals": [wrong_kind.data["id"]]},
        )


def test_greenfield_config_exercises_extracts_indexing_and_maintenance_paths(tmp_path: Path) -> None:
    _seed_greenfield_project(tmp_path)
    api = PlanningAPI(tmp_path)

    signal = api.create_with_content(
        "signal",
        label="Fresh trail",
        summary="Read signal",
        source="note-7",
        content="# Signal\n\nfresh\n",
    )
    sketch = api.create_with_content(
        "board",
        label="Facet map",
        summary="Shape route",
        content="# Concept\n\nmap\n\n# Edges\n\nsharp\n",
    )
    action = api.new("step", label="First move", summary="Execute move", domain="lab")

    api.relink(sketch.data["id"], "signal_refs", signal.data["id"])
    api.relink(action.data["id"], "sketch_ref", sketch.data["id"])
    api.relink(action.data["id"], "sketch_refs", sketch.data["id"], seq=100, display="primary")

    attachments_dir = tmp_path / "records" / "assets" / action.data["id"]
    attachments_dir.mkdir(parents=True, exist_ok=True)
    (attachments_dir / "diagram.png").write_text("png", encoding="utf-8")
    (attachments_dir / "resource-map.yaml").write_text(
        dedent(
            f"""
            owner: {action.data["id"]}
            owned:
              - src/greenfield/step.py
            related:
              - docs/ops/runbook.md
            """
        ).lstrip(),
        encoding="utf-8",
    )

    extract = api.extracts.extract(action.data["id"], with_related=True, with_resources=True)
    assert [Path(path).as_posix() for path in extract["attachments"]] == [
        f"records/assets/{action.data['id']}/diagram.png",
        f"records/assets/{action.data['id']}/resource-map.yaml",
    ]
    assert extract["related"]["sketch_ref"] == sketch.data["id"]
    assert extract["related"]["sketch_refs"] == [
        {"ref": sketch.data["id"], "seq": 100, "display": "primary"}
    ]
    assert api.extracts.owner("greenfield/step.py") == [
        {
            "owner": action.data["id"],
            "type": "owned",
            "path": "src/greenfield/step.py",
        }
    ]

    clean = api.clean_indexes()
    assert clean == {"indexes_rebuilt": True}
    assert (tmp_path / ".audiagentic" / "planning" / "indexes" / "intake.json").exists()
    assert (tmp_path / ".audiagentic" / "planning" / "indexes" / "sketches.json").exists()
    assert (tmp_path / ".audiagentic" / "planning" / "indexes" / "moves.json").exists()

    moved = api.move(action.data["id"], "field")
    assert moved.path == tmp_path / "records" / "atlas" / "moves" / "field" / "action-1-first-move.md"

    wrong = moved.path.with_name("action-1-wrong-name.md")
    moved.path.rename(wrong)
    maintain = api.maintain()
    assert len(maintain["renames"]) == 1
    assert api.lookup(action.data["id"]).path == (
        tmp_path / "records" / "atlas" / "moves" / "field" / "action-1-first-move.md"
    )

    rebaseline = api.rebaseline()
    assert rebaseline["indexes_rebuilt"] is True
    assert rebaseline["extracts_rebuilt"] == 3
    assert (
        tmp_path / ".audiagentic" / "planning" / "extracts" / f"{action.data['id']}.json"
    ).exists()


def test_greenfield_config_validation_reports_custom_semantic_failures(tmp_path: Path) -> None:
    _seed_greenfield_project(tmp_path)
    api = PlanningAPI(tmp_path)

    signal = api.new("signal", label="Loose thread", summary="Need child", source="brief-2")
    sketch = api.new("sketch", label="Open edge", summary="Need action")
    action = api.new("action", label="Broken move", summary="Bad ref", domain="lab")

    api.state(signal.data["id"], "triaged")
    api.state(signal.data["id"], "filed")
    api.state(sketch.data["id"], "approved")

    broken = api.lookup(action.data["id"])
    broken_data, broken_body = parse_markdown(broken.path)
    broken_data["sketch_ref"] = "sketch-999"
    dump_markdown(broken.path, broken_data, broken_body)

    invalid_path = tmp_path / "records" / "atlas" / "moves" / broken.path.name
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    broken.path.rename(invalid_path)

    errors = api.validate()
    assert any("signal in 'filed' state has no sketch references" in error for error in errors)
    assert any("sketch in 'approved' state has no action references" in error for error in errors)
    assert any("sketch_ref references non-existent sketch 'sketch-999'" in error for error in errors)
    assert any("action must be under moves/<domain>/" in error for error in errors)


def test_greenfield_soft_delete_uses_configured_field_names(tmp_path: Path) -> None:
    """Soft-delete writes configured field names, not hardcoded 'deleted'/'deleted_at'."""
    _seed_greenfield_project(tmp_path)
    planning_path = tmp_path / ".audiagentic" / "planning" / "config" / "planning.yaml"
    planning = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    planning["planning"]["soft_delete"] = {
        "flag_field": "removed",
        "timestamp_field": "removed_at",
        "reason_field": "removal_reason",
    }
    planning_path.write_text(yaml.safe_dump(planning, sort_keys=False), encoding="utf-8")

    api = PlanningAPI(tmp_path)
    signal = api.new("signal", label="To remove", summary="Drop later", source="brief-1")

    result = api.delete(signal.data["id"], reason="no longer needed")

    assert result["hard_delete"] is False
    assert "removed_at" in result
    assert "deleted_at" not in result

    raw, _ = parse_markdown(api.lookup(signal.data["id"]).path)
    assert raw["removed"] is True
    assert "removed_at" in raw
    assert raw["removal_reason"] == "no longer needed"
    assert "deleted" not in raw
    assert "deleted_at" not in raw


def test_greenfield_cascade_skipped_when_no_cascade_config(tmp_path: Path) -> None:
    """Lifecycle action without cascade config does not cascade — no hardcoded fallback."""
    _seed_greenfield_project(tmp_path)
    planning_path = tmp_path / ".audiagentic" / "planning" / "config" / "planning.yaml"
    planning = yaml.safe_load(planning_path.read_text(encoding="utf-8"))
    # Strip cascade from freeze action; keep transition_to
    planning["planning"]["lifecycle"]["actions"]["freeze"] = {"transition_to": "frozen"}
    planning_path.write_text(yaml.safe_dump(planning, sort_keys=False), encoding="utf-8")

    api = PlanningAPI(tmp_path)
    signal = api.new("signal", label="Lone signal", summary="Standalone", source="solo-1")
    sketch = api.new("sketch", label="Linked sketch", summary="Refs signal")
    api.relink(sketch.data["id"], "signal_refs", signal.data["id"])

    api.state(signal.data["id"], "frozen")

    assert api._find(signal.data["id"]).data["state"] == "frozen"
    # No cascade config -> sketch state unchanged (NOT auto-retired)
    assert api._find(sketch.data["id"]).data["state"] == "shaping"
