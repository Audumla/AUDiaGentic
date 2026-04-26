from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone

from ...fs.read import parse_markdown
from ...fs.write import dump_markdown


class ContentService:
    def __init__(self, api):
        self.api = api

    def update(
        self,
        id_: str,
        label: str | None = None,
        summary: str | None = None,
        body_append: str | None = None,
    ):
        item = self.api._find(id_)
        self.api.policy.assert_not_archived(item, "update")
        data, body = parse_markdown(item.path)
        if label:
            data["label"] = label
        if summary:
            data["summary"] = summary
        if body_append:
            body = body.rstrip() + "\n\n" + body_append.strip() + "\n"
        dump_markdown(item.path, data, body)

        self.api._publish_event(
            "planning.item.updated",
            {"id": id_, "kind": item.kind},
            {"triggered_by": "manual"},
        )

        self.api.reconcile()
        return self.api._find(id_)

    def get_content(self, id_: str) -> str:
        item = self.api._find(id_)
        _, body = parse_markdown(item.path)
        return body

    def update_content(
        self,
        id_: str,
        content: str,
        mode: str = "replace",
        section: str | None = None,
        position: int | None = None,
    ):
        item = self.api._find(id_)
        self.api.policy.assert_not_archived(item, "update content for")
        data, body = parse_markdown(item.path)

        if mode == "replace":
            body = content.rstrip() + "\n"
        elif mode == "append":
            body = body.rstrip() + "\n\n" + content.rstrip() + "\n"
        elif mode == "insert":
            if position is None:
                raise ValueError("position required for insert mode")
            lines = body.split("\n")
            if position < 1 or position > len(lines) + 1:
                raise ValueError(f"position {position} out of range (1-{len(lines) + 1})")
            lines.insert(position - 1, content.rstrip())
            body = "\n".join(lines) + "\n"
        elif mode == "section":
            if section is None:
                raise ValueError("section header required for section mode")
            section_pattern = re.compile(
                rf"^{re.escape(section)}\n\n(.*?)(?=\n#{1, 6}\s+|$)", re.M | re.S
            )
            match = section_pattern.search(body)
            if not match:
                body = body.rstrip() + f"\n\n{section}\n\n{content.rstrip()}\n"
            else:
                start = match.start()
                end = match.end()
                body = body[:start] + section + "\n\n" + content.rstrip() + "\n" + body[end:]
        else:
            raise ValueError(f"unknown mode: {mode}")

        dump_markdown(item.path, data, body)

        self.api._publish_event(
            "planning.item.updated",
            {"id": id_, "kind": item.kind},
            {"triggered_by": "manual"},
        )

        self.api.reconcile()
        return self.api._find(id_)

    def move(self, id_: str, domain: str):
        item = self.api._find(id_)
        self.api.policy.assert_not_archived(item, "move")
        if not self.api.config.kind_has_domain(item.kind):
            domain_kinds = [
                kind for kind in self.api.config.all_kinds() if self.api.config.kind_has_domain(kind)
            ]
            raise ValueError(
                f"kind '{item.kind}' cannot move by domain; configured domain kinds: {domain_kinds}"
            )
        dest_dir = self.api.paths.kind_dir(item.kind, domain)
        dest = dest_dir / item.path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.path), str(dest))
        self.api.reconcile()
        return self.api._find(id_)

    def delete(
        self,
        id_: str,
        hard: bool = False,
        reason: str | None = None,
    ) -> dict:
        item = self.api._find(id_)
        if hard:
            item.path.unlink(missing_ok=True)
            from ..id_gen import sync_counter

            sync_counter(self.api.root, item.kind)
            self.api.reconcile()
            result = {
                "id": id_,
                "hard_delete": True,
                "counter_sync": True,
            }
        else:
            data, body = parse_markdown(item.path)
            data["deleted"] = True
            data["deleted_at"] = datetime.now(timezone.utc).isoformat()
            if reason:
                data["deletion_reason"] = reason
            dump_markdown(item.path, data, body)
            self.api.index()
            result = {
                "id": id_,
                "hard_delete": False,
                "deleted_at": data["deleted_at"],
                "counter_sync": False,
            }
        self.api._publish_event(
            "planning.item.deleted",
            result,
            {"subject": {"kind": item.kind, "id": id_}, "triggered_by": "manual"},
        )
        return result
