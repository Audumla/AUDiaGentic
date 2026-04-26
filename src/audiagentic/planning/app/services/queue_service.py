from __future__ import annotations


class QueueService:
    def __init__(self, api):
        self.api = api

    def claim(self, kind: str, id_: str, holder: str, ttl: int | None = None):
        rec = self.api.claims_store.claim(kind, id_, holder, ttl)
        self.api.events.emit(f"{kind}.claimed", rec)
        self.api.index()
        return rec

    def unclaim(self, id_: str):
        ok = self.api.claims_store.unclaim(id_)
        if ok:
            self.api.events.emit("planning.unclaimed", {"id": id_})
            self.api.index()
        return ok

    def claims(self, kind: str | None = None):
        claims = self.api.claims_store.load()["claims"]
        return [c for c in claims if kind is None or c["kind"] == kind]

    def next_items(
        self, kind: str | None = None, state: str | None = None, domain: str | None = None
    ):
        defaults = self.api.config.queue_defaults()
        kind = kind or defaults["kind"]
        state = state or defaults["state"]
        items = [i for i in self.api._scan() if i.kind == kind and i.data["state"] == state]
        claimed = {c["id"] for c in self.claims()}
        out = []
        for item in items:
            if item.data["id"] in claimed:
                continue
            if item.data.get("deleted"):
                continue
            if domain and item.path.parent.name != domain:
                continue
            out.append(
                {
                    "id": item.data["id"],
                    "label": item.data["label"],
                    "path": str(item.path.relative_to(self.api.root)),
                }
            )
        return out
