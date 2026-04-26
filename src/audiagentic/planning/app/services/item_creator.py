from __future__ import annotations

from pathlib import Path

from ...fs.write import dump_markdown
from ..id_gen import next_id


class ItemCreatorService:
    def __init__(self, api):
        self.api = api

    def next_id_for_kind(self, kind: str) -> str:
        id_prefix = self.api.config.kind_id_prefix(kind)
        counter_file = self.api.config.kind_counter_file(kind)
        counter_path = self.api.root / ".audiagentic" / "planning" / "meta" / counter_file
        return next_id(counter_path=counter_path, id_prefix=id_prefix)

    def validate_required_refs(self, kind: str, required_refs: list[str], provided: dict) -> None:
        for ref_field in required_refs:
            value = provided.get(ref_field)
            if not value:
                raise ValueError(
                    f"Kind '{kind}' requires '{ref_field}' reference. "
                    f"Add it to planning.yaml kinds.{kind}.required_refs if this is incorrect."
                )

    def _creation_refs(self, kind: str, refs: dict[str, object] | None) -> dict[str, object]:
        values = dict(refs or {})
        standard_field = self.api.config.standard_ref_field()
        if standard_field not in values and kind in self.api.config.all_kinds():
            defaults = self.api.config.default_reference_values(kind, standard_field)
            if defaults:
                values[standard_field] = defaults
        return values

    def create_item_direct(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, object] | None = None,
        fields: dict[str, object] | None = None,
        profile: str | None = None,
        guidance: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        state: str | None = None,
    ) -> Path:
        frontmatter = self.api.frontmatter_builder.build(
            kind=kind,
            id_=id_,
            label=label,
            summary=summary,
            domain=domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
            state=state,
        )

        body = self.api.config.creation_template(kind, guidance=guidance, profile=profile)
        path = self.api.paths.kind_file(kind, id_, label, domain)
        dump_markdown(path, frontmatter, body)
        return path

    def create_item_with_manager(
        self,
        *,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None,
        workflow: str | None,
        refs: dict[str, object],
        fields: dict[str, object] | None,
        profile: str | None,
        guidance: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
        kind_config: dict,
    ) -> Path:
        has_domain = kind_config.get("has_domain", False)
        effective_domain = domain if has_domain else None

        frontmatter = self.api.frontmatter_builder.build(
            kind=kind,
            id_=id_,
            label=label,
            summary=summary,
            domain=effective_domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
        )

        relationship_errors = self.api.relationship_config.validate_refs(
            kind, frontmatter, validate_required=True
        )
        if relationship_errors:
            raise ValueError("; ".join(relationship_errors))

        validate_fields = self.api.config.validate_ref_fields_on_create(kind)
        if validate_fields:
            self.api.policy.validate_ref_fields(frontmatter, validate_fields)

        body = self.api.config.creation_template(kind, guidance=guidance, profile=profile)
        path = self.api.paths.kind_file(kind, id_, label, effective_domain)
        dump_markdown(path, frontmatter, body)

        self.api.relationships.sync_creation_back_refs(id_, kind, frontmatter)
        return path

    def create_generic_item(
        self,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        kind_config: dict,
        domain: str | None,
    ) -> Path:
        item_path = self.api.paths.kind_file(kind, id_, label, domain)
        item_path.parent.mkdir(parents=True, exist_ok=True)

        frontmatter = {
            "id": id_,
            "kind": kind,
            "label": label,
            "summary": summary,
            "state": self.api.config.initial_state(kind),
        }

        if domain:
            frontmatter["domain"] = domain

        body = self.api.config.creation_template(kind)
        dump_markdown(item_path, frontmatter, body)
        return item_path

    def new(
        self,
        kind: str,
        label: str,
        summary: str,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, object] | None = None,
        fields: dict[str, object] | None = None,
        profile: str | None = None,
        guidance: str | None = None,
        current_understanding: str | None = None,
        open_questions: list[str] | None = None,
        source: str | None = None,
        context: str | None = None,
        check_duplicates: bool = True,
    ):
        kind = self.api.config.normalize_kind(kind)

        try:
            kind_config = self.api.config.kind_config(kind)
        except ValueError:
            available = self.api.config.all_kinds()
            raise ValueError(
                f"Unknown kind '{kind}'. Add it to planning.yaml or use one of: {available}"
            )

        creation_refs = self._creation_refs(kind, refs)

        required_refs = kind_config.get("required_refs", [])
        self.validate_required_refs(kind, required_refs, creation_refs)

        if self.api.config.should_duplicate_check(kind) and check_duplicates:
            self.api.policy.check_duplicate(kind, label, summary)
        if self.api.config.requires_source_on_create(kind) and not source:
            raise ValueError(f"{kind} requires --source to track item origin")

        id_ = self.next_id_for_kind(kind)

        path = self.create_item_with_manager(
            kind=kind,
            id_=id_,
            label=label,
            summary=summary,
            domain=domain,
            workflow=workflow,
            refs=creation_refs,
            fields=fields,
            profile=profile,
            guidance=guidance,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
            kind_config=kind_config,
        )

        refinement_prefix = self.api.config.refinement_source_prefix(kind)
        if refinement_prefix and source and source.startswith(refinement_prefix):
            action_name = self.api.config.refinement_action(kind)
            if not action_name:
                raise ValueError(f"Kind '{kind}' refinement requires creation.refinement_action")
            superseded_id = source.removeprefix(refinement_prefix)
            self.api.planning_supersede.handle_refinement_source(superseded_id, id_, action_name)

        if profile:
            cascade = self.api.config.profile_cascade_targets(profile)
            for target_cfg in cascade:
                target_kind = target_cfg["kind"]
                if target_kind == kind:
                    continue
                label_suffix = target_cfg.get("label_suffix", "")
                summary_template = target_cfg.get("summary_template", "{source_summary}")
                target_domain = target_cfg.get("domain")
                target_id = self.next_id_for_kind(target_kind)
                target_kind_config = self.api.config.kind_config(target_kind)
                target_refs = self._render_mapping(
                    target_cfg.get("refs", {}),
                    source_kind=kind,
                    source_id=id_,
                    source_label=label,
                    source_summary=summary,
                    target_kind=target_kind,
                )
                self.create_item_with_manager(
                    kind=target_kind,
                    id_=target_id,
                    label=f"{label}{label_suffix}",
                    summary=self._render_template(
                        summary_template,
                        source_kind=kind,
                        source_id=id_,
                        source_label=label,
                        source_summary=summary,
                        target_kind=target_kind,
                    ),
                    domain=target_domain,
                    workflow=None,
                    refs=self._creation_refs(target_kind, target_refs),
                    fields=None,
                    profile=None,
                    guidance=None,
                    current_understanding=None,
                    open_questions=None,
                    source=None,
                    context=None,
                    kind_config=target_kind_config,
                )

        self.api._publish_event(
            "planning.item.created",
            {"id": id_, "kind": kind, "path": str(path.relative_to(self.api.root))},
            {"triggered_by": "manual"},
        )

        self.api.index()
        return self.api._find(id_)

    @staticmethod
    def _render_template(template: str, **values: object) -> str:
        return template.format(**values)

    def _render_mapping(self, mapping: dict, **values: object) -> dict[str, object]:
        rendered: dict[str, object] = {}
        for key, value in mapping.items():
            if isinstance(value, str):
                rendered[key] = self._render_template(value, **values)
            elif isinstance(value, list):
                rendered[key] = [
                    self._render_template(entry, **values) if isinstance(entry, str) else entry
                    for entry in value
                ]
            elif isinstance(value, dict):
                rendered[key] = self._render_mapping(value, **values)
            else:
                rendered[key] = value
        return rendered

    def create_with_content(
        self,
        kind: str,
        label: str,
        summary: str,
        content: str,
        source: str | None = None,
        domain: str | None = None,
        workflow: str | None = None,
        refs: dict[str, object] | None = None,
        fields: dict[str, object] | None = None,
        check_duplicates: bool = True,
    ):
        kind = self.api.config.normalize_kind(kind)

        creation_refs = self._creation_refs(kind, refs)

        if self.api.config.should_duplicate_check(kind) and check_duplicates:
            self.api.policy.check_duplicate(kind, label, summary)
        required_refs = self.api.config.kind_config(kind).get("required_refs", [])
        self.validate_required_refs(kind, required_refs, creation_refs)
        if self.api.config.requires_source_on_create(kind) and not source:
            raise ValueError(f"{kind} requires source to track item origin")

        id_ = self.next_id_for_kind(kind)
        kind_config = self.api.config.kind_config(kind)

        try:
            path = self.create_item_with_manager(
                kind=kind,
                id_=id_,
                label=label,
                summary=summary,
                domain=domain,
                workflow=workflow,
                refs=creation_refs,
                fields=fields,
                profile=None,
                guidance=None,
                current_understanding=None,
                open_questions=None,
                source=source,
                context=None,
                kind_config=kind_config,
            )
            self.api.update_content(id_, content)
        except Exception:
            if "path" in locals() and Path(path).exists():
                Path(path).unlink(missing_ok=True)
            raise

        self.api._publish_event(
            "planning.item.created",
            {"id": id_, "kind": kind, "path": str(path.relative_to(self.api.root))},
            {"triggered_by": "manual"},
        )

        self.api.index()
        return self.api._find(id_)
