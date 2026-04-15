from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from .config import KnowledgeConfig
from .utils import load_yaml_file

Handler = Callable[..., Any]


def load_handler(import_path: str) -> Handler:
    module_name, sep, attr_name = import_path.partition(':')
    if not sep or not module_name or not attr_name:
        raise ValueError(f'Invalid handler path: {import_path}')
    module = import_module(module_name)
    handler = getattr(module, attr_name, None)
    if handler is None or not callable(handler):
        raise ValueError(f'Handler not found or not callable: {import_path}')
    return handler


def load_registry(path: Path, section: str) -> dict[str, dict[str, Any]]:
    data = load_yaml_file(path, {})
    if not isinstance(data, dict):
        return {}
    records = data.get(section, {})
    if not isinstance(records, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in records.items():
        if isinstance(value, dict):
            normalized[str(key)] = {str(k): v for k, v in value.items()}
    return normalized


def resolve_registry_handler(registry: dict[str, dict[str, Any]], key: str) -> tuple[Handler, dict[str, Any]]:
    record = registry.get(key)
    if not record:
        raise ValueError(f'Registry key not found: {key}')
    handler_path = str(record.get('handler', '')).strip()
    if not handler_path:
        raise ValueError(f'Registry entry has no handler: {key}')
    handler = load_handler(handler_path)
    defaults = record.get('defaults', {})
    return handler, defaults if isinstance(defaults, dict) else {}


def load_importer_registry(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.importer_registry_file, 'importer_strategies')


def load_event_action_registry(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.action_registry_file, 'event_actions')


def load_action_registry(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.action_registry_file, 'deterministic_actions')


def load_execution_registry(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.execution_registry_file, 'tasks')


def load_llm_provider_registry(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.llm_registry_file, 'providers')


def load_llm_profiles(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.llm_registry_file, 'profiles')


def load_llm_task_policies(config: KnowledgeConfig) -> dict[str, dict[str, Any]]:
    return load_registry(config.llm_registry_file, 'task_policies')
