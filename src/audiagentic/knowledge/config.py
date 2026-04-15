from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import load_yaml_file

DEFAULT_CONFIG_PATH = ".audiagentic/knowledge/config.yml"
CONFIG_ENV_VAR = "AUDIAGENTIC_KNOWLEDGE_CONFIG"


@dataclass(slots=True)
class KnowledgeConfig:
    root: Path
    raw: dict[str, Any]
    config_path: Path

    @property
    def knowledge_root(self) -> Path:
        return self.root / str(self.raw.get("knowledge_root", "knowledge"))

    @property
    def pages_root(self) -> Path:
        return self.knowledge_root / str(self.raw.get("pages_dir", "pages"))

    @property
    def meta_root(self) -> Path:
        return self.knowledge_root / str(self.raw.get("meta_dir", "meta"))

    @property
    def proposals_root(self) -> Path:
        return self.knowledge_root / str(self.raw.get("proposals_dir", "proposals"))

    @property
    def archive_root(self) -> Path:
        return self.knowledge_root / str(self.raw.get("archive_dir", "archive"))

    @property
    def state_root(self) -> Path:
        return self.knowledge_root / str(self.raw.get("state_dir", "state"))

    @property
    def sync_state_file(self) -> Path:
        return self.state_root / str(self.raw.get("sync_state_file", "sync-state.yml"))

    @property
    def snapshots_root(self) -> Path:
        return self.state_root / str(self.raw.get("snapshots_dir", "snapshots"))

    @property
    def event_state_file(self) -> Path:
        return self.state_root / str(self.raw.get("event_state_file", "event-state.yml"))

    @property
    def event_journal_file(self) -> Path:
        return self.state_root / str(self.raw.get("event_journal_file", "event-journal.ndjson"))

    @property
    def llm_job_state_file(self) -> Path:
        return self.state_root / str(self.raw.get("llm_job_state_file", "llm-jobs.yml"))

    @property
    def hook_config_file(self) -> Path:
        rel = self.raw.get("hook_config_file", "sync/hooks.yml")
        return self.knowledge_root / str(rel)

    @property
    def event_adapter_file(self) -> Path:
        rel = self.raw.get("events", {}).get("adapters_file", "events/adapters.yml")
        return self.config_path.parent / str(rel)

    @property
    def importer_registry_file(self) -> Path:
        rel = self.raw.get("importer_registry_file", "registries/importers.yml")
        return self.knowledge_root / str(rel)

    @property
    def action_registry_file(self) -> Path:
        rel = self.raw.get("action_registry_file", "registries/actions.yml")
        return self.knowledge_root / str(rel)

    @property
    def llm_registry_file(self) -> Path:
        rel = self.raw.get("llm_registry_file", "registries/llm.yml")
        return self.knowledge_root / str(rel)

    @property
    def navigation_config_file(self) -> Path:
        rel = self.raw.get("navigation_config_file", "navigation/routes.yml")
        return self.knowledge_root / str(rel)

    @property
    def execution_registry_file(self) -> Path:
        rel = self.raw.get("execution_registry_file", "registries/execution.yml")
        return self.knowledge_root / str(rel)

    @property
    def docs_root(self) -> Path:
        rel = self.raw.get("docs_root", "docs")
        return self.knowledge_root / str(rel)

    @property
    def templates_root(self) -> Path:
        rel = self.raw.get("templates_root", "templates")
        return self.knowledge_root / str(rel)

    @property
    def import_manifest_root(self) -> Path:
        rel = self.raw.get("import_manifest_dir", "import/manifests")
        return self.knowledge_root / str(rel)

    @property
    def allowed_types(self) -> list[str]:
        return [str(t) for t in self.raw.get("page_types", [])]

    @property
    def required_metadata(self) -> list[str]:
        return [str(x) for x in self.raw.get("required_metadata", [])]

    @property
    def required_sections(self) -> list[str]:
        return [str(x) for x in self.raw.get("required_sections", [])]

    @property
    def related_field(self) -> str:
        return str(self.raw.get("related_field", "related"))

    @property
    def allow_archived_links(self) -> bool:
        return bool(self.raw.get("allow_archived_links", False))

    @property
    def search_weights(self) -> dict[str, float]:
        weights = self.raw.get("search", {}).get("weights", {})
        return {
            "title": float(weights.get("title", 4.0)),
            "tags": float(weights.get("tags", 3.0)),
            "sections": float(weights.get("sections", 2.0)),
            "body": float(weights.get("body", 1.0)),
        }

    @property
    def snippet_length(self) -> int:
        return int(self.raw.get("search", {}).get("snippet_length", 200))

    @property
    def page_type_dirs(self) -> dict[str, str]:
        mapping = self.raw.get("page_type_dirs", {})
        return {str(k): str(v) for k, v in mapping.items()}

    @property
    def stale_statuses(self) -> list[str]:
        values = self.raw.get("sync", {}).get(
            "stale_statuses", ["changed", "missing", "untracked", "manual_stale"]
        )
        return [str(x) for x in values]

    @property
    def auto_hook_allowed_states(self) -> list[str]:
        values = self.raw.get("sync", {}).get(
            "auto_hook_allowed_states", ["implemented", "verified", "active", "current"]
        )
        return [str(x) for x in values]

    @property
    def diff_context_lines(self) -> int:
        return int(self.raw.get("sync", {}).get("diff_context_lines", 2))

    @property
    def diff_max_lines(self) -> int:
        return int(self.raw.get("sync", {}).get("diff_max_lines", 80))

    @property
    def proposal_default_mode(self) -> str:
        return str(self.raw.get("sync", {}).get("proposal_default_mode", "review_only"))

    @property
    def auto_apply_proposals(self) -> bool:
        return bool(self.raw.get("events", {}).get("auto_apply_proposals", True))

    @property
    def auto_mark_stale(self) -> bool:
        return bool(self.raw.get("events", {}).get("auto_mark_stale", True))

    @property
    def handlers_file(self) -> Path:
        rel = self.raw.get("events", {}).get("handlers_file", "events/handlers.yml")
        return self.config_path.parent / str(rel)

    @property
    def scaffold_default_sections(self) -> list[str]:
        return [
            str(x)
            for x in self.raw.get("scaffolding", {}).get("default_sections", self.required_sections)
        ]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.raw.get("llm", {}).get("enabled", False))

    @property
    def llm_default_provider(self) -> str:
        return str(self.raw.get("llm", {}).get("default_provider", "disabled"))

    @property
    def llm_default_mode(self) -> str:
        return str(self.raw.get("llm", {}).get("default_mode", "blocking"))

    @property
    def selected_profiles(self) -> dict[str, str]:
        value = self.raw.get("selected_profiles", {})
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    @property
    def runtime_contract(self) -> dict[str, Any]:
        value = self.raw.get("runtime_contract", {})
        return value if isinstance(value, dict) else {}

    @property
    def runtime_settings(self) -> dict[str, Any]:
        value = self.raw.get("runtime", {})
        return value if isinstance(value, dict) else {}

    @property
    def bootstrap_contract_paths(self) -> list[str]:
        paths = [
            str(self.config_path.relative_to(self.root)),
            ".audiagentic/knowledge/profiles/selected.yml",
            str(self.importer_registry_file.relative_to(self.root)),
            str(self.action_registry_file.relative_to(self.root)),
            str(self.execution_registry_file.relative_to(self.root)),
            str(self.llm_registry_file.relative_to(self.root)),
            str(self.navigation_config_file.relative_to(self.root)),
            str(self.hook_config_file.relative_to(self.root)),
            str(self.event_adapter_file.relative_to(self.root)),
            str(self.handlers_file.relative_to(self.root)),
        ]
        return paths


def resolve_config_path(root: Path, config_path: str | Path | None = None) -> Path:
    if config_path:
        candidate = Path(config_path)
        return candidate if candidate.is_absolute() else (root / candidate)
    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        candidate = Path(env_path)
        return candidate if candidate.is_absolute() else (root / candidate)
    return root / DEFAULT_CONFIG_PATH


def load_config(root: Path, config_path: str | Path | None = None) -> KnowledgeConfig:
    resolved = resolve_config_path(root, config_path)
    data = load_yaml_file(resolved, {})
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config format in {resolved}")
    return KnowledgeConfig(root=root, raw=data, config_path=resolved)
