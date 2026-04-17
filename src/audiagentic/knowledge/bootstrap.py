from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_defaults import get_capability_contract, get_capability_profiles, get_host_profiles
from .utils import dump_yaml


def bootstrap_project(
    target_root: Path,
    *,
    knowledge_root: str = 'knowledge',
    config_relpath: str = '.audiagentic/knowledge/config.yml',
    force: bool = False,
    capability_profile: str = 'deterministic-minimal',
    host_profile: str = 'mcp-stdio',
) -> dict[str, Any]:
    created: list[str] = []
    root = target_root.resolve()
    config_path = root / config_relpath
    capability_profiles = get_capability_profiles()
    host_profiles = get_host_profiles()
    if capability_profile not in capability_profiles:
        raise ValueError(f'Unknown capability profile: {capability_profile}')
    if host_profile not in host_profiles:
        raise ValueError(f'Unknown host profile: {host_profile}')

    config = _base_config(knowledge_root, config_relpath)
    _deep_merge(config, capability_profiles[capability_profile].get('config_overrides', {}))
    _deep_merge(config, host_profiles[host_profile].get('config_overrides', {}))
    config['selected_profiles'] = {
        'capability_profile': capability_profile,
        'host_profile': host_profile,
    }
    config['runtime_contract'] = get_capability_contract()

    knowledge_path = root / knowledge_root
    files: dict[Path, str] = {
        config_path: dump_yaml(config),
        root / '.audiagentic' / 'knowledge' / 'profiles' / 'selected.yml': dump_yaml({'capability_profile': capability_profile, 'host_profile': host_profile}),
        knowledge_path / 'registries' / 'importers.yml': dump_yaml(_default_importers()),
        knowledge_path / 'registries' / 'actions.yml': dump_yaml(_default_actions()),
        knowledge_path / 'registries' / 'execution.yml': dump_yaml(_default_execution()),
        knowledge_path / 'registries' / 'llm.yml': dump_yaml(_default_llm()),
        knowledge_path / 'navigation' / 'routes.yml': dump_yaml(_default_navigation()),
        knowledge_path / 'sync' / 'hooks.yml': dump_yaml(_default_hooks()),
        knowledge_path / 'events' / 'adapters.yml': dump_yaml({'adapters': []}),
        knowledge_path / 'import' / 'manifests' / 'seed.yml': dump_yaml({'items': []}),
        knowledge_path / 'index.md': '# Knowledge Index\n\nThis vault stores current-state project knowledge.\n',
        knowledge_path / 'log.md': '# Knowledge Log\n\nRecord high-level maintenance notes here if needed.\n',
        knowledge_path / 'docs' / 'README.md': _docs_readme(config_relpath, knowledge_root),
        knowledge_path / 'templates' / 'page-template.md': _page_template(),
        knowledge_path / 'templates' / 'page-sidecar.meta.yml': _page_sidecar_template(),
    }
    for path, content in files.items():
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        created.append(str(path.relative_to(root)))
    for rel in [
        'pages/systems', 'pages/guides', 'pages/tools', 'pages/patterns', 'pages/decisions', 'pages/glossary', 'pages/runbooks',
        'meta/systems', 'meta/guides', 'meta/tools', 'meta/patterns', 'meta/decisions', 'meta/glossary', 'meta/runbooks',
        'proposals', 'archive', 'state/snapshots', 'source_material', 'docs', 'templates', 'registries', 'sync', 'events', 'import/manifests', 'navigation'
    ]:
        path = knowledge_path / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path.relative_to(root)) + '/')
    return {
        'root': str(root),
        'created': sorted(dict.fromkeys(created)),
        'config_path': str(config_path.relative_to(root)),
        'selected_profiles': {'capability_profile': capability_profile, 'host_profile': host_profile},
    }


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _base_config(knowledge_root: str, config_relpath: str) -> dict[str, Any]:
    return {
        'knowledge_root': knowledge_root,
        'pages_dir': 'pages',
        'meta_dir': 'meta',
        'proposals_dir': 'proposals',
        'archive_dir': 'archive',
        'state_dir': 'state',
        'sync_state_file': 'sync-state.yml',
        'snapshots_dir': 'snapshots',
        'event_state_file': 'event-state.yml',
        'event_journal_file': 'event-journal.ndjson',
        'llm_job_state_file': 'llm-jobs.yml',
        'hook_config_file': 'sync/hooks.yml',
        'event_adapter_file': 'events/adapters.yml',
        'import_manifest_dir': 'import/manifests',
        'importer_registry_file': 'registries/importers.yml',
        'action_registry_file': 'registries/actions.yml',
        'execution_registry_file': 'registries/execution.yml',
        'llm_registry_file': 'registries/llm.yml',
        'navigation_config_file': 'navigation/routes.yml',
        'docs_root': 'docs',
        'templates_root': 'templates',
        'page_types': ['system', 'guide', 'tool', 'pattern', 'decision', 'glossary_term', 'runbook'],
        'required_metadata': ['id', 'title', 'type', 'status', 'summary', 'owners', 'updated_at'],
        'required_sections': ['Summary', 'Current state', 'How to use', 'Sync notes', 'References'],
        'related_field': 'related',
        'allow_archived_links': False,
        'page_type_dirs': {
            'system': 'systems',
            'guide': 'guides',
            'tool': 'tools',
            'pattern': 'patterns',
            'decision': 'decisions',
            'glossary_term': 'glossary',
            'runbook': 'runbooks',
        },
        'search': {'snippet_length': 220, 'weights': {'title': 4.0, 'tags': 3.0, 'sections': 2.0, 'body': 1.0}},
        'scaffolding': {'default_sections': ['Summary', 'Current state', 'How to use', 'Sync notes', 'References']},
        'sync': {'stale_statuses': ['changed', 'missing', 'untracked', 'manual_stale'], 'auto_hook_allowed_states': ['implemented', 'verified', 'active', 'current'], 'diff_context_lines': 2, 'diff_max_lines': 80, 'diff_excerpt_lines': 12, 'proposal_default_mode': 'review_only', 'proposal_retention_days': 30, 'archive_retention_days': 90},
        'llm': {'enabled': False, 'default_provider': 'disabled', 'default_mode': 'blocking', 'job_retention_days': 7},
        'runtime': {
            'capability_id': 'knowledge',
            'contract_version': 'v0.7',
            'config_relpath': config_relpath,
            'project_mode': 'pre_installer_aligned',
            'expose_mcp_stdio': True,
        },
    }


def _default_importers() -> dict[str, Any]:
    return {
        'importer_strategies': {
            'markdown_doc': {'handler': 'audiagentic_knowledge.importers:import_markdown_doc'},
            'yaml_config': {'handler': 'audiagentic_knowledge.importers:import_yaml_config'},
            'ndjson_events': {'handler': 'audiagentic_knowledge.importers:import_ndjson_events'},
            'json_snapshot': {'handler': 'audiagentic_knowledge.importers:import_json_snapshot'},
        }
    }


def _default_actions() -> dict[str, Any]:
    return {
        'event_actions': {
            'generate_sync_proposal': {'handler': 'audiagentic_knowledge.events:action_generate_sync_proposal'},
            'mark_stale': {'handler': 'audiagentic_knowledge.events:action_mark_stale'},
            'mark_stale_and_generate_sync_proposal': {'handler': 'audiagentic_knowledge.events:action_mark_stale_and_generate_sync_proposal'},
            'ignore': {'handler': 'audiagentic_knowledge.events:action_ignore'},
        },
        'deterministic_actions': {
            'scan_drift': {'handler': 'audiagentic_knowledge.actions:action_scan_drift'},
            'generate_sync_proposals': {'handler': 'audiagentic_knowledge.actions:action_generate_sync_proposals'},
            'cleanup_lifecycle': {'handler': 'audiagentic_knowledge.actions:action_cleanup_lifecycle'},
            'record_sync': {'handler': 'audiagentic_knowledge.actions:action_record_sync'},
            'scan_events': {'handler': 'audiagentic_knowledge.actions:action_scan_events'},
            'process_events': {'handler': 'audiagentic_knowledge.actions:action_process_events'},
            'record_event_baseline': {'handler': 'audiagentic_knowledge.actions:action_record_event_baseline'},
            'seed_from_manifest': {'handler': 'audiagentic_knowledge.actions:action_seed_from_manifest'},
            'scaffold_page': {'handler': 'audiagentic_knowledge.actions:action_scaffold_page'},
            'search_pages': {'handler': 'audiagentic_knowledge.actions:action_search_pages'},
            'doctor': {'handler': 'audiagentic_knowledge.actions:action_doctor'},
        },
    }


def _default_execution() -> dict[str, Any]:
    return {
        'tasks': {
            'answer_question': {
                'deterministic_handler': 'audiagentic_knowledge.llm:deterministic_answer_question',
                'provider': 'disabled',
                'profile': 'knowledge-deep-answer',
                'mode': 'blocking',
                'allow_llm': True,
                'fallback': 'return_candidates_and_gaps',
            },
            'draft_sync_proposal': {
                'deterministic_handler': 'audiagentic_knowledge.llm:deterministic_draft_sync_proposal',
                'provider': 'disabled',
                'profile': 'knowledge-proposal',
                'mode': 'blocking',
                'allow_llm': True,
                'fallback': 'return_patch_skeleton',
            },
            'bootstrap_project_knowledge': {
                'deterministic_handler': 'audiagentic_knowledge.llm:deterministic_bootstrap_project_knowledge',
                'provider': 'disabled',
                'profile': 'knowledge-bootstrap-scan',
                'mode': 'async',
                'allow_llm': True,
                'fallback': 'return_seed_inventory',
            },
        },
    }


def _default_llm() -> dict[str, Any]:
    return {
        'providers': {
            'disabled': {'handler': 'audiagentic_knowledge.llm:provider_disabled'},
            'mock_overseer': {'handler': 'audiagentic_knowledge.llm:provider_mock_overseer', 'defaults': {'supports_async': True, 'supports_blocking': True}},
            'openai_compatible_remote': {'handler': 'audiagentic_knowledge.llm:provider_disabled', 'defaults': {'note': 'Placeholder registry entry for a future remote provider adapter.'}},
        },
        'profiles': {
            'knowledge-triage': {'description': 'Small fast profile for classification and source triage.', 'capabilities': ['classification', 'reranking', 'short_summary'], 'supports_blocking': True, 'supports_async': True, 'structured_output': True, 'citation_friendly': True},
            'knowledge-proposal': {'description': 'Structured proposal drafting profile.', 'capabilities': ['proposal_synthesis', 'diff_summary'], 'supports_blocking': True, 'supports_async': True, 'structured_output': True, 'citation_friendly': True},
            'knowledge-deep-answer': {'description': 'Broader synthesis profile for answering questions over retrieved pages.', 'capabilities': ['question_answering', 'topic_brief'], 'supports_blocking': True, 'supports_async': True, 'structured_output': True, 'citation_friendly': True},
            'knowledge-bootstrap-scan': {'description': 'Asynchronous interrogation profile for larger project scans.', 'capabilities': ['repo_interrogation', 'entity_extraction', 'relation_extraction'], 'supports_blocking': False, 'supports_async': True, 'structured_output': True, 'citation_friendly': True},
        },
    }


def _default_navigation() -> dict[str, Any]:
    return {
        'routes': [
            {'id': 'registry_and_current_state', 'label': 'Current operational state', 'keywords': ['registry', 'build status', 'current state', 'claim', 'verified'], 'page_ids': [], 'deterministic_actions': ['scan_drift', 'generate_sync_proposals'], 'note': 'Use this route for current operational docs and sync review.'},
            {'id': 'runtime_events', 'label': 'Runtime event artifacts', 'keywords': ['runtime', 'events', 'stream', 'ndjson'], 'page_ids': [], 'deterministic_actions': ['scan_events', 'process_events'], 'note': 'Use this route when runtime artifacts may have changed.'},
        ],
        'fallbacks': [
            {'action_id': 'search_pages', 'keywords': ['find', 'where', 'what page'], 'label': 'Search pages', 'note': 'Lexical search across current-state pages.'},
            {'action_id': 'scan_drift', 'keywords': ['drift', 'stale', 'sync'], 'label': 'Scan drift', 'note': 'Deterministic fallback when sources may have changed.'},
            {'action_id': 'scan_events', 'keywords': ['event', 'runtime'], 'label': 'Scan events', 'note': 'Deterministic fallback for runtime/planning event artifacts.'},
            {'action_id': 'doctor', 'keywords': ['doctor', 'health', 'install'], 'label': 'Doctor', 'note': 'Check the capability contract and project-owned files.'},
        ],
    }


def _default_hooks() -> dict[str, Any]:
    return {
        'hooks': [
            {'id': 'current-state-doc-change', 'kind': 'file_change', 'applies_to': ['**/*.md', '**/*.yaml', '**/*.yml'], 'eligibility': {'reject_when_path_contains': ['requests', 'draft', 'proposals'], 'reject_when_content_contains': ['DRAFT'], 'allow_when_content_contains_any': ['VERIFIED', 'active', 'current']}, 'action': 'generate_sync_proposal', 'note': 'Conservative default hook policy.'},
            {'id': 'runtime-artifact-change', 'kind': 'runtime_event_stream', 'applies_to': ['**/*.ndjson', '**/*.json'], 'eligibility': {'source_maturity': 'runtime_current'}, 'action': 'generate_sync_proposal', 'note': 'Runtime artifacts feed review proposals rather than silent current-state rewrites.'},
        ]
    }


def _docs_readme(config_relpath: str, knowledge_root: str) -> str:
    return f"""# AUDiaGentic Knowledge Component

This is an installable current-state knowledge capability intended for use inside any project.

## Runtime vs project ownership

Runtime-owned:
- CLI commands, validators, importer/action/execution defaults, MCP server, and host profiles.

Project-owned:
- the vault under `{knowledge_root}/`, sidecars, state, manifests, hooks, event adapters, and proposals.

## Contract

- Primary docs stay human-readable.
- Sidecar metadata and state live beside the docs under `{knowledge_root}/`.
- Behavior is driven from config at `{config_relpath}`.
- Registries, hooks, navigation, manifests, and event adapters are all YAML-driven.
- Higher-level tasks use a deterministic execution registry first.
- Optional provider use is layered behind the deterministic contract and may remain disabled.
- This capability is aligned to the future `audiagentic knowledge ...` CLI shape even before the wider installer exists.

## First actions

1. Edit the import manifest under `{knowledge_root}/import/manifests/seed.yml`.
2. Edit hooks under `{knowledge_root}/sync/hooks.yml`.
3. Edit navigation routes under `{knowledge_root}/navigation/routes.yml`.
4. Edit registries under `{knowledge_root}/registries/`.
5. Run the CLI to seed, scan drift, process events, answer questions, and run `doctor`.
6. Rebind deterministic task handlers in `registries/execution.yml` before introducing any optional provider.
"""


def _page_template() -> str:
    return """## Summary
Current-state summary goes here.

## Current state
Describe how this works now.

## How to use
Describe how a human or agent should use this now.

## Sync notes
Describe how this page is refreshed and what it follows.

## References
- Add supporting references here.
"""


def _page_sidecar_template() -> str:
    return dump_yaml({'id': 'know-example-page', 'title': 'Example Page', 'type': 'guide', 'status': 'active', 'summary': 'Current-state summary.', 'owners': ['core'], 'tags': [], 'related': [], 'updated_at': 'YYYY-MM-DD', 'source_refs': []})
