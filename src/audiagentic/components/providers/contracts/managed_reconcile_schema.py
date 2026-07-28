"""Single source of truth for the managed-reconcile JSON Schema envelope.

The managed-mcp and managed-hooks automation families share one real shape
(``{ownership_scope, entries[]}`` in / ``{ok, supported, changed,
managed_ids, removed_ids, collision_ids, action_needed, error_code}`` out) —
same ownership (providers component), same lifecycle (config-reconcile),
same semantics. That's genuine duplication (PC07 step 3), so it's factored
here once instead of hand-duplicated across 4 JSON files.

The other managed-* style families (plugin-entry, language-server-projection,
model-projection) are intentionally NOT folded in here — each has a real
shape difference (singular entry vs list, dict-keyed entries, extra domain
fields, different result verbs), so sharing this envelope would pad them
with fields that don't apply. See the code-cleanup CC51 boundary rule:
consolidate only when ownership+lifecycle+semantics genuinely match.

``contracts/provider-managed-{mcp,hooks}-{payload,result}.schema.json`` are
GENERATED from the builders below — run this module as a script to
regenerate; ``test_managed_reconcile_schema_files_match_generator`` is the
drift guard that keeps the checked-in files honest.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONTRACTS_DIR = Path(__file__).resolve().parent

MCP_ENTRY_ITEM: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["managed_id", "name"],
    "properties": {
        "managed_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "command": {"type": "string", "minLength": 1},
        "args": {"type": "array", "items": {"type": "string"}},
        "env": {"type": "object", "additionalProperties": {"type": "string"}},
        "url": {"type": "string", "minLength": 1},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "transport": {"enum": ["http", "sse"]},
    },
    "oneOf": [
        {"required": ["command"], "not": {"required": ["url"]}},
        {"required": ["url"], "not": {"required": ["command"]}},
    ],
}

HOOKS_ENTRY_ITEM: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["managed_id", "event", "command"],
    "properties": {
        "managed_id": {"type": "string", "minLength": 1},
        "event": {"type": "string", "minLength": 1},
        "command": {"type": "string", "minLength": 1},
        "timeout": {"type": "integer"},
    },
}


def _payload_schema(id_: str, entry_item: dict[str, Any]) -> dict[str, Any]:
    """The shared managed-reconcile payload envelope: {ownership_scope, entries[]}."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": id_,
        "type": "object",
        "additionalProperties": False,
        "required": ["ownership_scope", "entries"],
        "properties": {
            "ownership_scope": {"type": "string", "minLength": 1},
            "entries": {"type": "array", "items": entry_item},
        },
    }


def _result_schema(
    id_: str,
    *,
    extra_properties: dict[str, Any] | None = None,
    extra_required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The shared managed-reconcile result envelope core fields."""
    properties: dict[str, Any] = {
        "ok": {"type": "boolean"},
        "supported": {"type": "boolean"},
        "provider_id": {"type": "string"},
        "changed": {"type": "boolean"},
        "managed_ids": {"type": "array", "items": {"type": "string"}},
        "removed_ids": {"type": "array", "items": {"type": "string"}},
        "collision_ids": {"type": "array", "items": {"type": "string"}},
        "action_needed": {"type": ["string", "null"]},
        "error_code": {"type": ["string", "null"]},
    }
    if extra_properties:
        properties.update(extra_properties)
    required = [
        "ok", "supported", "changed", "managed_ids", "removed_ids",
        "collision_ids", "action_needed", "error_code", *extra_required,
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": id_,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def build_managed_mcp_payload_schema() -> dict[str, Any]:
    return _payload_schema("provider-managed-mcp-payload/v1", MCP_ENTRY_ITEM)


def build_managed_mcp_result_schema() -> dict[str, Any]:
    return _result_schema(
        "provider-managed-mcp-result/v1",
        extra_properties={"auto_refreshed": {"type": "boolean"}},
        extra_required=("auto_refreshed",),
    )


def build_managed_hooks_payload_schema() -> dict[str, Any]:
    return _payload_schema("provider-managed-hooks-payload/v1", HOOKS_ENTRY_ITEM)


def build_managed_hooks_result_schema() -> dict[str, Any]:
    return _result_schema("provider-managed-hooks-result/v1")


GENERATED_SCHEMA_FILES: dict[str, Any] = {
    "provider-managed-mcp-payload.schema.json": build_managed_mcp_payload_schema,
    "provider-managed-mcp-result.schema.json": build_managed_mcp_result_schema,
    "provider-managed-hooks-payload.schema.json": build_managed_hooks_payload_schema,
    "provider-managed-hooks-result.schema.json": build_managed_hooks_result_schema,
}


def generated_schema_text(filename: str) -> str:
    return json.dumps(GENERATED_SCHEMA_FILES[filename](), indent=2) + "\n"


if __name__ == "__main__":
    for filename in GENERATED_SCHEMA_FILES:
        (_CONTRACTS_DIR / filename).write_text(generated_schema_text(filename), encoding="utf-8")
        print(f"wrote {filename}")
