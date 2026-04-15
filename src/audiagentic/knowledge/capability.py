from __future__ import annotations

from typing import Any

from .config import KnowledgeConfig
from .runtime_defaults import get_capability_contract, get_capability_profiles, get_host_profiles


def show_install_profiles() -> dict[str, Any]:
    return {
        'capability_profiles': get_capability_profiles(),
        'host_profiles': get_host_profiles(),
    }


def show_capability_contract(config: KnowledgeConfig | None = None) -> dict[str, Any]:
    contract = get_capability_contract()
    payload: dict[str, Any] = {'runtime_contract': contract}
    if config is not None:
        payload['project_alignment'] = {
            'config_path': str(config.config_path.relative_to(config.root)),
            'knowledge_root': str(config.knowledge_root.relative_to(config.root)),
            'selected_profiles': config.selected_profiles,
            'runtime_settings': config.runtime_settings,
        }
    return payload


def doctor(config: KnowledgeConfig) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for rel_path in config.bootstrap_contract_paths:
        path = config.root / rel_path
        checks.append({'name': f'exists:{rel_path}', 'ok': path.exists(), 'path': rel_path})
    checks.append({'name': 'knowledge_root_exists', 'ok': config.knowledge_root.exists(), 'path': str(config.knowledge_root.relative_to(config.root))})
    checks.append({'name': 'pages_root_exists', 'ok': config.pages_root.exists(), 'path': str(config.pages_root.relative_to(config.root))})
    checks.append({'name': 'meta_root_exists', 'ok': config.meta_root.exists(), 'path': str(config.meta_root.relative_to(config.root))})
    selected = config.selected_profiles
    capability_profiles = get_capability_profiles()
    host_profiles = get_host_profiles()
    checks.append({'name': 'capability_profile_known', 'ok': selected.get('capability_profile') in capability_profiles, 'value': selected.get('capability_profile')})
    checks.append({'name': 'host_profile_known', 'ok': selected.get('host_profile') in host_profiles, 'value': selected.get('host_profile')})
    contract = get_capability_contract()
    checks.append({'name': 'contract_version_matches', 'ok': str(config.runtime_settings.get('contract_version', '')) == str(contract.get('contract_version', '')), 'expected': contract.get('contract_version'), 'actual': config.runtime_settings.get('contract_version')})
    ok = all(item.get('ok') for item in checks)
    return {
        'ok': ok,
        'checks': checks,
        'selected_profiles': selected,
        'runtime_contract': contract,
    }
