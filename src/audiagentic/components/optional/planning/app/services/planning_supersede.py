from __future__ import annotations

from datetime import datetime, timezone

from ...fs.read import parse_markdown
from ...fs.write import dump_markdown


class PlanningSupersedeService:
    """Planning-domain service for handling item supersede relationships.

    Encapsulates planning-specific semantics around refinement detection and
    supersede linkage. Separated from generic LifecycleService which handles
    only state transitions and cascades.
    """

    def __init__(self, api):
        self.api = api

    def handle_refinement_source(self, superseded_id: str, new_id: str, action_name: str) -> None:
        """Mark old item as superseded when new item refinement source pattern detected.

        Called from ItemCreatorService when source matches refinement_source_prefix.
        """
        self._apply_supersede(superseded_id, new_id, action_name)

    def _apply_supersede(self, superseded_id: str, new_id: str, action_name: str) -> None:
        """Apply configured supersede action linking old and new items.

        Raises ValueError if required action config is missing.
        """
        action = self.api.config.lifecycle_action(action_name)
        extensions = action.get("extensions")
        if not isinstance(extensions, dict):
            raise ValueError(f"lifecycle action '{action_name}' requires extensions config")
        extension = extensions.get("planning_supersede")
        if not isinstance(extension, dict):
            raise ValueError(
                f"lifecycle action '{action_name}' requires extensions.planning_supersede config"
            )

        reason_template = extension.get("reason_template")
        if not reason_template:
            raise ValueError(f"supersede action '{action_name}' missing required reason_template")
        reason = reason_template.format(new_id=new_id)

        superseded_by_field = extension.get("superseded_by_field")
        if not superseded_by_field:
            raise ValueError(f"supersede action '{action_name}' missing required superseded_by_field")

        body_template = extension.get("body_note_template")
        body_section = extension.get("body_note_section")
        if not body_template:
            raise ValueError(f"supersede action '{action_name}' missing required body_note_template")
        if not body_section:
            raise ValueError(f"supersede action '{action_name}' missing required body_note_section")
        now_iso = datetime.now(timezone.utc).isoformat()
        note = body_template.format(new_id=new_id, date=now_iso)

        superseded = self.api._find(superseded_id)
        parse_markdown(superseded.path)
        new_item = self.api._find(new_id)
        new_data, new_body = parse_markdown(new_item.path)

        supersedes_field = extension.get("supersedes_field")
        if not supersedes_field:
            raise ValueError(f"supersede action '{action_name}' missing required supersedes_field")

        self.api.lifecycle.apply_action(action_name, superseded_id, reason=reason, actor="system")

        superseded = self.api._find(superseded_id)
        data, body = parse_markdown(superseded.path)
        if "meta" not in data:
            data["meta"] = {}
        data["meta"][superseded_by_field] = new_id

        if body_section in body:
            body = body.rstrip() + note + "\n"
        else:
            body = body.rstrip() + "\n\n" + body_section + "\n\n" + note + "\n"

        dump_markdown(superseded.path, data, body)

        if "meta" not in new_data:
            new_data["meta"] = {}
        new_data["meta"][supersedes_field] = superseded_id

        dump_markdown(new_item.path, new_data, new_body)
        self.api.index()
