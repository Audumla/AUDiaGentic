from __future__ import annotations

import shutil


class MaintenanceService:
    def __init__(self, api):
        self.api = api

    def validate(self, raise_on_error: bool = False):
        errors = self.api.validator.validate_all()
        if raise_on_error and errors:
            raise RuntimeError("\n".join(errors))
        return errors

    def index(self):
        self.api.indexer.write_indexes()

    def rebaseline(self) -> dict:
        idx_dir = self.api.root / ".audiagentic/planning/indexes"
        if idx_dir.exists():
            shutil.rmtree(idx_dir)
            idx_dir.mkdir(parents=True)

        ext_dir = self.api.root / ".audiagentic/planning/extracts"
        if ext_dir.exists():
            shutil.rmtree(ext_dir)
            ext_dir.mkdir(parents=True)

        self.api.indexer.write_indexes()

        items = self.api._scan()
        rebuilt = 0
        skipped = []
        for item in items:
            if not self.api.config.is_soft_deleted(item.data):
                try:
                    self.api.extracts.extract(
                        item.data["id"],
                        with_related=False,
                        with_resources=False,
                        include_body=True,
                        write_to_disk=True,
                    )
                    rebuilt += 1
                except ValueError as e:
                    skipped.append({"id": item.data["id"], "error": str(e)})

        return {
            "indexes_rebuilt": True,
            "extracts_rebuilt": rebuilt,
            "extracts_skipped": len(skipped),
            "skipped_items": skipped,
            "total_items": len(items),
        }

    def clean_indexes(self) -> dict:
        idx_dir = self.api.root / ".audiagentic/planning/indexes"
        if idx_dir.exists():
            shutil.rmtree(idx_dir)
            idx_dir.mkdir(parents=True)

        self.api.indexer.write_indexes()

        self.api._publish_event(
            "planning.indexes_cleaned",
            {"indexes_rebuilt": True},
            {"triggered_by": "manual"},
        )

        return {"indexes_rebuilt": True}

    def maintain(self) -> dict:
        reconcile_result = self.api.reconciler.run()
        rebaseline_result = self.rebaseline()

        self.api._publish_event(
            "planning.maintained",
            {
                "renames": len(reconcile_result["renames"]),
                "orphans": reconcile_result["orphans"],
                "indexes_rebuilt": rebaseline_result["indexes_rebuilt"],
                "extracts_rebuilt": rebaseline_result["extracts_rebuilt"],
                "extracts_skipped": rebaseline_result["extracts_skipped"],
            },
            {"triggered_by": "manual"},
        )

        return {
            "renames": reconcile_result["renames"],
            "orphans": reconcile_result["orphans"],
            **rebaseline_result,
        }

    def compact(self) -> dict:
        result = self.api.compactor.run()
        if not result.get("aborted"):
            self.rebaseline()
        self.api._publish_event(
            "planning.compacted",
            {
                "remapped": result["remapped"],
                "renames": len(result["renames"]),
                "repair_count": result["repair_count"],
                "aborted": bool(result.get("aborted")),
            },
            {"triggered_by": "manual"},
        )
        return result

    def reconcile(self):
        result = self.maintain()
        self.api._publish_event(
            "planning.reconciled",
            {"renames": len(result["renames"]), "orphans": result["orphans"]},
            {"triggered_by": "manual"},
        )
        return {"renames": result["renames"], "orphans": result["orphans"]}

