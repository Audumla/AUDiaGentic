from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ..fs.scan import scan_items
from .config import _PLANNING_SCHEMA_DIR, Config
from .util import body_has_section


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.schemas = _PLANNING_SCHEMA_DIR
        self.config = Config(root)

    def _get_required_sections(self, kind: str) -> list[str]:
        """Get required sections for a kind from config."""
        return self.config.required_sections(kind) or []

    def validate_all(self) -> list[str]:
        errors = []
        errors.extend(self.config.validate())
        items = list(scan_items(self.root))
        ids = set()

        # Build indexes for referential integrity checks
        specs_by_request = {}  # request_id -> [spec_ids]
        tasks_by_spec = {}  # spec_id -> [task_ids]

        for item in items:
            if item.kind == "spec" and not item.data.get("deleted"):
                for req_id in item.data.get("request_refs", []):
                    if req_id not in specs_by_request:
                        specs_by_request[req_id] = []
                    specs_by_request[req_id].append(item.data["id"])
            elif item.kind == "task" and not item.data.get("deleted"):
                spec_ref = item.data.get("spec_ref")
                if spec_ref:
                    if spec_ref not in tasks_by_spec:
                        tasks_by_spec[spec_ref] = []
                    tasks_by_spec[spec_ref].append(item.data["id"])

        for item in items:
            if item.data["id"] in ids:
                errors.append(f"duplicate id: {item.data['id']}")
            ids.add(item.data["id"])
            schema_name = {
                "request": "request.schema.json",
                "spec": "specification.schema.json",
                "plan": "plan.schema.json",
                "task": "task.schema.json",
                "wp": "work-package.schema.json",
                "standard": None,
            }[item.kind]
            sch = None
            if schema_name:
                sch = json.loads((self.schemas / schema_name).read_text(encoding="utf-8"))
                v = Draft202012Validator(sch)
                for e in v.iter_errors(item.data):
                    errors.append(f"{item.path}: {self._format_error(e)}")
            allowed = (
                set((sch.get("properties", {}) if sch else {}).keys())
                if sch
                else set(item.data.keys())
            )
            for k in item.data.keys():
                if sch and k not in allowed:
                    errors.append(f"{item.path}: forbidden top-level field '{k}', use meta")
            if item.kind in {"request", "task"}:
                if item.path.name != f"{item.data['id']}.md":
                    errors.append(f"{item.path}: filename must be {item.data['id']}.md")
            elif item.kind in {"spec", "plan", "wp", "standard"}:
                if not item.path.name.startswith(item.data["id"]):
                    errors.append(f"{item.path}: filename must start with {item.data['id']}")
        # Check sections and path structure (single pass)
        for item in items:
            # Check guidance-appropriate sections
            if item.kind == "request" and item.data.get("guidance"):
                guidance = item.data["guidance"]
                guidance_cfg = self.config.guidance_levels().get(guidance, {})
                spec_sections = guidance_cfg.get("spec_sections", {})
                task_sections = guidance_cfg.get("task_sections", {})

                if item.kind == "spec":
                    required = spec_sections.get("required", [])
                    for sec in required:
                        if not body_has_section(item.body, sec):
                            errors.append(
                                f"{item.path}: missing required section '{sec}' for {guidance} guidance"
                            )
                elif item.kind == "task":
                    required = task_sections.get("required", [])
                    for sec in required:
                        if not body_has_section(item.body, sec):
                            errors.append(
                                f"{item.path}: missing required section '{sec}' for {guidance} guidance"
                            )

            # Check required sections for kind
            for sec in self._get_required_sections(item.kind):
                if not body_has_section(item.body, sec):
                    errors.append(f"{item.path}: missing section '{sec}'")

            # Check path structure
            if item.kind == "task":
                if item.path.parent.parent.name != "tasks":
                    errors.append(f"{item.path}: task must be under docs/planning/tasks/<domain>/")
            if item.kind == "wp":
                if item.path.parent.parent.name != "work-packages":
                    errors.append(
                        f"{item.path}: wp must be under docs/planning/work-packages/<domain>/"
                    )

        # Referential integrity checks
        for item in items:
            if item.data.get("deleted"):
                continue
            if item.data.get("state") == "archived":
                continue

            # Specs must have at least one request reference (request-012)
            if item.kind == "spec":
                request_refs = item.data.get("request_refs", []) or []
                if not request_refs:
                    errors.append(
                        f"{item.path}: spec has no request references (orphan spec is not allowed)"
                    )
                else:
                    # Verify all request refs exist
                    for req_id in request_refs:
                        found = any(i.data["id"] == req_id and i.kind == "request" for i in items)
                        if not found:
                            errors.append(
                                f"{item.path}: spec references non-existent request '{req_id}'"
                            )

            # Requests in distilled/ready/done state should have specs
            if item.kind == "request" and item.data.get("state") in (
                "distilled",
                "ready",
                "done",
            ):
                req_id = item.data["id"]
                if req_id not in specs_by_request or not specs_by_request[req_id]:
                    errors.append(
                        f"{item.path}: request in '{item.data['state']}' state has no spec references"
                    )

            # Specs in ready/done state should have tasks
            if item.kind == "spec" and item.data.get("state") in ("ready", "done"):
                spec_id = item.data["id"]
                if spec_id not in tasks_by_spec or not tasks_by_spec[spec_id]:
                    errors.append(
                        f"{item.path}: spec in '{item.data['state']}' state has no task references"
                    )

        return errors

    def _format_error(self, error: ValidationError) -> str:
        path_parts = [str(part) for part in error.path]
        field = path_parts[0] if path_parts else None

        rel_fields = {"task_refs", "work_package_refs"}
        if (
            error.validator == "type"
            and field in rel_fields
            and len(path_parts) >= 2
            and isinstance(error.instance, str)
        ):
            example = (
                f"{field} must be a list of objects with 'ref' and optional 'seq'/'display'. "
                f"Expected example: - ref: {error.instance}\n  seq: 1000\n"
                f"Got: {error.instance}"
            )
            return example

        if error.validator == "required" and path_parts:
            missing = ", ".join(repr(part) for part in error.validator_value)
            return f"{field or 'item'} is missing required field(s): {missing}"

        if error.validator == "additionalProperties":
            field_name = field or "item"
            return f"{field_name} has unsupported fields; move custom values into meta when appropriate"

        if field in rel_fields:
            return f"{field}: {error.message}"

        if field:
            return f"{field}: {error.message}"
        return error.message
