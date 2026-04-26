from __future__ import annotations


class FrontmatterBuilder:
    def __init__(self, config):
        self.config = config

    def build(
        self,
        *,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None,
        workflow: str | None,
        refs: dict[str, object] | None,
        fields: dict[str, object] | None,
        profile: str | None,
        guidance: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
        state: str | None = None,
    ) -> dict:
        if guidance is None:
            guidance = self.config.default_guidance()

        frontmatter = {
            "id": id_,
            "label": label,
            "state": state or self.config.initial_state(kind, workflow),
            "summary": summary,
        }

        if domain:
            frontmatter["domain"] = domain

        input_values = dict(refs or {})
        seed_field_sources = self.config.seeded_reference_fields(kind)

        for field in self.config.reference_fields(kind):
            if field in input_values:
                value = input_values.get(field)
            elif field in seed_field_sources:
                value = input_values.get(seed_field_sources[field])
            elif self.config.reference_field_shape(field) == "rel_list":
                value = []
            else:
                value = None
            value = self._coerce_reference_value(field, value)

            if value in (None, [], ""):
                continue
            frontmatter[field] = value

        if workflow:
            frontmatter["workflow"] = workflow

        frontmatter.update(
            self.config.build_creation_extra_fields(
                kind,
                summary=summary,
                guidance=guidance,
                profile=profile,
                current_understanding=current_understanding,
                open_questions=open_questions,
                source=source,
                context=context,
            )
        )
        for field, value in (fields or {}).items():
            if value not in (None, [], ""):
                frontmatter[field] = value

        return frontmatter

    def _coerce_reference_value(self, field: str, value):
        if value is None:
            return None
        shape = self.config.reference_field_shape(field)
        if shape == "scalar_ref_list" and isinstance(value, str):
            return [value]
        if shape == "scalar_ref" and isinstance(value, list):
            return value[0] if len(value) == 1 else None
        if shape == "rel_list":
            if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
                return [{"ref": v, "seq": (i + 1) * 1000} for i, v in enumerate(value)]
        return value
