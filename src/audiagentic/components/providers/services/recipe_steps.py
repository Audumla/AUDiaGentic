"""Provider-layer recipe step types — the shielded seam for recipes.

These steps let a declarative recipe materialize provider-owned configuration
(MCP entries, hooks, plugin entries) **through the managed family**, never by
raw-writing a provider file (USING_RECIPES.md §6, the managed-vs-raw boundary).
They live here, not in ``foundation/steps``, so foundation stays domain-neutral;
they self-register into the step factory when the providers component imports.

Each step reads its ``project_root`` from the recipe execution context and is
self-reverting: ``run`` applies (or prunes/status per ``mode``); ``compensate``
prunes what ``run`` applied. This module is also the template for any component
that needs its own specialized step — register a builder + schema fragment via
``register_step_type`` from the owning layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from audiagentic.foundation.steps.factory import register_step_type, strict_substitute
from audiagentic.foundation.steps.results import StepResult

_ID = {"type": "string", "minLength": 1}


def _substituter(step_id: str, params: dict[str, str] | None):
    def sub(value: Any) -> Any:
        if params is None:
            return value
        if isinstance(value, str):
            return strict_substitute(value, params, f"step.{step_id}")
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        return value

    return sub


class _ManagedProviderStep:
    """Base for steps that reconcile provider config through a managed family."""

    def __init__(self, id: str, provider_id: str, *, mode: str = "apply") -> None:
        self.id = id
        self.provider_id = provider_id
        self.mode = mode
        self._applied = False

    # Subclasses implement the family call for a given mode and a summary dict.
    def _reconcile(self, project_root: Path, mode: str) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def _summary(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _project_root(self, context: dict[str, Any]) -> Path:
        root = context.get("project_root")
        if root is None:
            raise ValueError(f"{type(self).__name__} requires 'project_root' in the recipe context")
        return Path(root)

    def run(self, context: dict[str, Any]) -> StepResult:
        result = self._reconcile(self._project_root(context), self.mode)
        if self.mode == "apply":
            self._applied = True
        ok = bool(getattr(result, "ok", False))
        # Stash family result for lifecycle reporting (DE03).
        # Uses a list so multiple managed-* steps in one recipe all contribute;
        # the last entry is the primary managed result for _lifecycle_hint.
        bucket = context.setdefault("managed_results", [])
        if hasattr(result, "to_mapping"):
            bucket.append(result.to_mapping())
        return StepResult(
            status="ok" if ok else "failed",
            outputs={**self._summary(), "mode": self.mode},
            reason=None if ok else getattr(result, "error_code", "managed reconcile failed"),
        )

    def compensate(self, context: dict[str, Any]) -> StepResult:
        if not self._applied:
            return StepResult(status="skipped", reason="run never applied")
        self._reconcile(self._project_root(context), "prune")
        return StepResult(status="ok", outputs={**self._summary(), "pruned": True})

    def plan(self, context: dict[str, Any]) -> StepResult:
        return StepResult(status="planned", outputs={**self._summary(), "mode": self.mode})


# ---------------------------------------------------------------------------
# managed-mcp
# ---------------------------------------------------------------------------

_MANAGED_MCP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "id", "provider", "managed-id", "ownership-scope", "name"],
    "properties": {
        "type": {"const": "managed-mcp"},
        "id": _ID,
        "provider": _ID,
        "managed-id": _ID,
        "ownership-scope": _ID,
        "name": _ID,
        "mode": {"enum": ["apply", "prune", "status"]},
        "url": _ID,
        "transport": {"enum": ["http", "sse"]},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "command": _ID,
        "args": {"type": "array", "items": {"type": "string"}},
        "env": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


class ManagedMcpStep(_ManagedProviderStep):
    def __init__(self, id, provider_id, ownership_scope, entry, *, mode="apply"):
        super().__init__(id, provider_id, mode=mode)
        self.ownership_scope = ownership_scope
        self.entry = entry

    def _reconcile(self, project_root, mode):
        from audiagentic.components.providers.contracts.managed_mcp import (
            ManagedMcpEntry,
            ManagedMcpMode,
            ManagedMcpRequest,
        )
        from audiagentic.components.providers.providers_api import manage_mcp_entries

        entries = () if mode == "prune" else (ManagedMcpEntry.from_mapping(self.entry),)
        return manage_mcp_entries(
            project_root,
            self.provider_id,
            mode=cast(ManagedMcpMode, mode),
            request=ManagedMcpRequest(ownership_scope=self.ownership_scope, entries=entries),
        )

    def _summary(self):
        return {"provider": self.provider_id, "managed_id": self.entry.get("managed_id")}


def _build_managed_mcp(data, params=None):
    sub = _substituter(data.get("id", "managed-mcp"), params)
    entry: dict[str, Any] = {"managed_id": data["managed-id"], "name": sub(data["name"])}
    if data.get("url"):
        entry["url"] = sub(data["url"])
        entry["transport"] = data.get("transport", "http")
        if data.get("headers"):
            hdrs = {k: sub(v) for k, v in data["headers"].items()}
            hdrs = {k: v for k, v in hdrs.items() if v}  # drop empty values
            if hdrs:
                entry["headers"] = hdrs
    elif data.get("command"):
        entry["command"] = sub(data["command"])
        if data.get("args"):
            entry["args"] = sub(data["args"])
        if data.get("env"):
            env = {k: sub(v) for k, v in data["env"].items()}
            env = {k: v for k, v in env.items() if v}  # drop empty values
            if env:
                entry["env"] = env
    return ManagedMcpStep(
        id=data.get("id", "managed-mcp"),
        provider_id=sub(data["provider"]),
        ownership_scope=sub(data["ownership-scope"]),
        entry=entry,
        mode=data.get("mode", "apply"),
    )


# ---------------------------------------------------------------------------
# managed-hooks
# ---------------------------------------------------------------------------

_MANAGED_HOOKS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "id", "provider", "ownership-scope", "entries"],
    "properties": {
        "type": {"const": "managed-hooks"},
        "id": _ID,
        "provider": _ID,
        "ownership-scope": _ID,
        "mode": {"enum": ["apply", "prune", "status"]},
        "entries": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["managed-id", "event", "command"],
                "properties": {
                    "managed-id": _ID,
                    "event": _ID,
                    "command": _ID,
                    "timeout": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}


class ManagedHooksStep(_ManagedProviderStep):
    def __init__(self, id, provider_id, ownership_scope, entries, *, mode="apply"):
        super().__init__(id, provider_id, mode=mode)
        self.ownership_scope = ownership_scope
        self.entries = entries

    def _reconcile(self, project_root, mode):
        from audiagentic.components.providers.contracts.managed_hooks import (
            ManagedHooksEntry,
            ManagedHooksMode,
            ManagedHooksRequest,
        )
        from audiagentic.components.providers.providers_api import manage_hook_entries

        entries = (
            ()
            if mode == "prune"
            else tuple(ManagedHooksEntry.from_mapping(e) for e in self.entries)
        )
        return manage_hook_entries(
            project_root,
            self.provider_id,
            mode=cast(ManagedHooksMode, mode),
            request=ManagedHooksRequest(ownership_scope=self.ownership_scope, entries=entries),
        )

    def _summary(self):
        return {
            "provider": self.provider_id,
            "hook_ids": [e.get("managed_id") for e in self.entries],
        }


def _build_managed_hooks(data, params=None):
    sub = _substituter(data.get("id", "managed-hooks"), params)
    entries = [
        {
            "managed_id": e["managed-id"],
            "event": sub(e["event"]),
            "command": sub(e["command"]),
            **({"timeout": e["timeout"]} if e.get("timeout") is not None else {}),
        }
        for e in data["entries"]
    ]
    return ManagedHooksStep(
        id=data.get("id", "managed-hooks"),
        provider_id=sub(data["provider"]),
        ownership_scope=sub(data["ownership-scope"]),
        entries=entries,
        mode=data.get("mode", "apply"),
    )


# ---------------------------------------------------------------------------
# managed-plugin
# ---------------------------------------------------------------------------

_MANAGED_PLUGIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "id", "provider", "entry-id", "ownership-scope"],
    "properties": {
        "type": {"const": "managed-plugin"},
        "id": _ID,
        "provider": _ID,
        "entry-id": _ID,
        "ownership-scope": _ID,
        "mode": {"enum": ["apply", "prune", "status"]},
        "options": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


class ManagedPluginStep(_ManagedProviderStep):
    def __init__(self, id, provider_id, entry_id, ownership_scope, options, *, mode="apply"):
        super().__init__(id, provider_id, mode=mode)
        self.entry_id = entry_id
        self.ownership_scope = ownership_scope
        self.options = options

    def _reconcile(self, project_root, mode):
        from audiagentic.components.providers.contracts.plugin_entry import (
            PluginEntryMode,
            PluginEntryRequest,
        )
        from audiagentic.components.providers.providers_api import manage_plugin_entry

        return manage_plugin_entry(
            project_root,
            self.provider_id,
            mode=cast(PluginEntryMode, mode),
            request=PluginEntryRequest(
                entry_id=self.entry_id,
                ownership_scope=self.ownership_scope,
                options=tuple(sorted(self.options.items())),
            ),
        )

    def _summary(self):
        return {"provider": self.provider_id, "entry_id": self.entry_id}


def _build_managed_plugin(data, params=None):
    sub = _substituter(data.get("id", "managed-plugin"), params)
    return ManagedPluginStep(
        id=data.get("id", "managed-plugin"),
        provider_id=sub(data["provider"]),
        entry_id=sub(data["entry-id"]),
        ownership_scope=sub(data["ownership-scope"]),
        options={str(k): str(sub(v)) for k, v in dict(data.get("options", {})).items()},
        mode=data.get("mode", "apply"),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_PROVIDER_STEPS = (
    ("managed-mcp", _build_managed_mcp, _MANAGED_MCP_SCHEMA),
    ("managed-hooks", _build_managed_hooks, _MANAGED_HOOKS_SCHEMA),
    ("managed-plugin", _build_managed_plugin, _MANAGED_PLUGIN_SCHEMA),
)


def register_provider_steps() -> None:
    """Register provider-layer step types into the foundation step factory.

    Idempotent: safe to call on every providers-component import.
    """
    from audiagentic.foundation.steps.factory import registered_types

    existing = set(registered_types())
    for name, builder, schema in _PROVIDER_STEPS:
        if name not in existing:
            register_step_type(name, builder, schema=schema, accepts_params=True)


__all__ = [
    "ManagedMcpStep",
    "ManagedHooksStep",
    "ManagedPluginStep",
    "register_provider_steps",
]
