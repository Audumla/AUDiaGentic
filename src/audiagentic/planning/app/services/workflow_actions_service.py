from __future__ import annotations

import json
from pathlib import Path

from ...fs.read import parse_markdown
from ...fs.write import dump_markdown
from ..api_types import ItemView
from ..reference_inheritance import effective_references
from .workflow_action_executor import WorkflowActionExecutor, render


class WorkflowActionsService:
    def __init__(self, api):
        self.api = api
        self.executor = WorkflowActionExecutor(api)

    def execute_action(self, action_name: str, context: dict):
        """Execute a configured workflow action with the given typed context."""
        return self.executor.execute(action_name, context)

    def apply_plan_overlay(
        self,
        label: str,
        summary: str,
        spec_id: str,
        task_ids: list[str],
        request_refs: list[str] | None = None,
        domain: str | None = None,
    ):
        return self.executor.execute(
            "plan_overlay",
            {
                "label": label,
                "summary": summary,
                "spec_id": spec_id,
                "task_ids": task_ids,
                "request_refs": request_refs or [],
                "domain": domain,
            },
        )

    def package(
        self,
        plan_ref: str,
        task_ids: list[str],
        label: str,
        summary: str,
        domain: str | None = None,
        workflow: str | None = None,
    ):
        existing = self._find_existing_package(plan_ref, task_ids, label, summary, domain, workflow)
        if existing is not None:
            return existing

        result = self.executor.execute(
            "package",
            {
                "parent_id": plan_ref,
                "item_ids": task_ids,
                "label": label,
                "summary": summary,
                "domain": domain,
                "workflow": workflow,
            },
        )
        keys = list(result.keys())
        return result[keys[0]] if len(keys) == 1 else result

    def _find_existing_package(
        self,
        parent_id: str,
        item_ids: list[str],
        label: str,
        summary: str,
        domain: str | None,
        workflow: str | None,
    ):
        action = self.api.config.workflow_action("package")
        create_key, spec = next(iter(action.get("creates", {}).items()))
        context = self._action_context(action, {
            "parent_id": parent_id,
            "item_ids": item_ids,
            "label": label,
            "summary": summary,
            "domain": domain,
            "workflow": workflow,
        })
        kind = render(spec["kind"], context)
        refs = render(spec.get("refs", {}), context) or {}
        frontmatter = self.api.frontmatter_builder.build(
            kind=kind,
            id_="match-candidate",
            label=label,
            summary=summary,
            domain=render(spec.get("domain"), context),
            workflow=render(spec.get("workflow"), context),
            refs=refs,
            fields=None,
            profile=None,
            guidance=None,
            current_understanding=None,
            open_questions=None,
            source=None,
            context=None,
        )

        parent_fields = [
            field for field in self.api.config.reference_fields(kind)
            if parent_id in self.api.relationships.iter_ref_ids(frontmatter.get(field))
        ]
        child_fields = [
            field for field in self.api.config.reference_fields(kind)
            if set(item_ids).issubset(set(self.api.relationships.iter_ref_ids(frontmatter.get(field))))
        ]
        if not parent_fields or not child_fields:
            return None

        for item in self.api._scan():
            if item.kind != kind or item.data.get("deleted"):
                continue
            if item.data.get("label") != label:
                continue
            if domain and item.data.get("domain") != domain:
                continue
            if all(item.data.get(field) == frontmatter.get(field) for field in parent_fields):
                self.api.relationships.merge_rel_refs(item.data["id"], child_fields[0], item_ids)
                return self.api._find(item.data["id"])
        return None

    @staticmethod
    def _action_context(action: dict, context: dict) -> dict:
        full_context = dict(context)
        for param, default_value in action.get("defaults", {}).items():
            key = f"{param}_or_default"
            full_context[key] = context[param] if context.get(param) is not None else default_value
        return full_context

    def add_rel_ref(self, parent_id: str, field: str, child_id: str):
        parent_item = self.api._find(parent_id)
        if field in self.api.config.reference_fields(parent_item.kind):
            data, body = parse_markdown(parent_item.path)
            existing_refs = {r["ref"]: r for r in data.get(field, [])}
            if child_id not in existing_refs:
                seq = max((r["seq"] for r in existing_refs.values()), default=999) + 1000
                existing_refs[child_id] = {"ref": child_id, "seq": seq}
                data[field] = sorted(existing_refs.values(), key=lambda x: x["seq"])
                dump_markdown(parent_item.path, data, body)

    def effective_refs(self, id_: str, field: str | None = None):
        items = {
            item.data["id"]: ItemView(item.kind, item.path, item.data, item.body)
            for item in self.api._scan()
        }
        return effective_references(
            items[id_],
            field or self.api.config.standard_ref_field(),
            items,
            self.api.config,
        )

    def dump_all(self, output_dir: str | None = None, format_: str = "json") -> dict:
        import yaml

        items = self.api._scan()
        docs = []

        for item in items:
            data, body = parse_markdown(item.path)
            docs.append(
                {
                    "id": data["id"],
                    "kind": item.kind,
                    "path": str(item.path.relative_to(self.api.root)),
                    "frontmatter": data,
                    "body": body,
                }
            )

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            dumped = 0
            for doc in docs:
                if format_ == "json":
                    file_path = out_path / f"{doc['id']}.json"
                    file_path.write_text(
                        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                else:
                    file_path = out_path / f"{doc['id']}.yaml"
                    file_path.write_text(
                        yaml.dump(doc, default_flow_style=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                dumped += 1

            return {"dumped": dumped, "output_dir": str(output_dir), "format": format_}

        if format_ == "json":
            print_json(docs)
        else:
            print(yaml.dump(docs, default_flow_style=False, allow_unicode=True))

        return {"dumped": len(docs), "output": "stdout", "format": format_}


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))
