from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from .config import KnowledgeConfig
from .markdown_io import load_page_by_id
from .navigation import suggest_navigation
from .registry import (
    load_execution_registry,
    load_handler,
    load_llm_profiles,
    load_llm_provider_registry,
    resolve_registry_handler,
)
from .search import search_pages
from .sync import generate_sync_proposals, scan_drift
from .utils import dump_yaml, load_yaml_file, now_utc

DEFAULT_TASKS: dict[str, dict[str, Any]] = {
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
}


def load_llm_job_state(config: KnowledgeConfig) -> dict[str, Any]:
    data = load_yaml_file(config.llm_job_state_file, {'jobs': {}})
    if not isinstance(data, dict):
        return {'jobs': {}}
    data.setdefault('jobs', {})
    return data


def save_llm_job_state(config: KnowledgeConfig, state: dict[str, Any]) -> None:
    config.llm_job_state_file.parent.mkdir(parents=True, exist_ok=True)
    config.llm_job_state_file.write_text(dump_yaml(state), encoding='utf-8')


def list_profiles(config: KnowledgeConfig) -> dict[str, Any]:
    profiles = load_llm_profiles(config)
    active_provider = config.llm_default_provider
    return {
        'provider_enabled': config.llm_enabled,
        'active_provider': active_provider,
        'profiles': [
            {
                'profile_id': profile_id,
                'capabilities': list(profile.get('capabilities', []) or []),
                'supports_blocking': bool(profile.get('supports_blocking', True)),
                'supports_async': bool(profile.get('supports_async', False)),
                'structured_output': bool(profile.get('structured_output', False)),
                'citation_friendly': bool(profile.get('citation_friendly', True)),
                'description': profile.get('description'),
            }
            for profile_id, profile in sorted(profiles.items())
        ],
    }


def show_execution_registry(config: KnowledgeConfig) -> dict[str, Any]:
    return {'tasks': load_execution_registry(config) or DEFAULT_TASKS}


def answer_question(config: KnowledgeConfig, question: str, *, limit: int = 8, allow_llm: bool | None = None, mode: str | None = None) -> dict[str, Any]:
    payload = {'question': question, 'limit': limit}
    return _run_task(config, 'answer_question', payload, allow_llm=allow_llm, mode=mode)


def draft_sync_proposal(config: KnowledgeConfig, *, page_id: str | None = None, allow_llm: bool | None = None, mode: str | None = None) -> dict[str, Any]:
    payload = {'page_id': page_id}
    return _run_task(config, 'draft_sync_proposal', payload, allow_llm=allow_llm, mode=mode)


def bootstrap_project_knowledge(config: KnowledgeConfig, *, manifest: str | None = None, allow_llm: bool | None = None, mode: str | None = None) -> dict[str, Any]:
    payload = {'manifest': manifest}
    return _run_task(config, 'bootstrap_project_knowledge', payload, allow_llm=allow_llm, mode=mode)


def submit_profile_job(config: KnowledgeConfig, task_name: str, payload: dict[str, Any], *, mode: str = 'async', allow_llm: bool | None = None) -> dict[str, Any]:
    policy = _resolve_task_config(config, task_name, allow_llm=allow_llm, mode=mode)
    if not policy['use_llm']:
        return {
            'task_name': task_name,
            'outcome': 'unavailable',
            'execution': {'path': 'deterministic_only', 'mode': policy['mode'], 'used_llm': False, 'provider': policy['provider'], 'profile': policy['profile']},
            'message': 'No optional provider is configured for this task.',
        }
    provider_result = _call_provider(config, policy, task_name=task_name, payload=payload)
    state = load_llm_job_state(config)
    job_id = provider_result.get('job_id') or _make_job_id(task_name, payload)
    state['jobs'][job_id] = {
        'task_name': task_name,
        'submitted_at': now_utc().isoformat(),
        'provider': policy['provider'],
        'profile': policy['profile'],
        'mode': policy['mode'],
        'status': provider_result.get('status', 'completed'),
        'request': payload,
        'result': provider_result.get('result'),
        'message': provider_result.get('message'),
    }
    save_llm_job_state(config, state)
    return {
        'task_name': task_name,
        'outcome': 'queued' if policy['mode'] == 'async' else 'llm_assisted_complete',
        'execution': {'path': 'optional_provider', 'mode': policy['mode'], 'used_llm': True, 'provider': policy['provider'], 'profile': policy['profile']},
        'job_id': job_id,
        'status': state['jobs'][job_id]['status'],
        'message': provider_result.get('message'),
    }


def get_job_status(config: KnowledgeConfig, job_id: str) -> dict[str, Any]:
    state = load_llm_job_state(config)
    job = state.get('jobs', {}).get(job_id)
    if not job:
        raise ValueError(f'Job not found: {job_id}')
    return {'job_id': job_id, 'status': job.get('status'), 'task_name': job.get('task_name'), 'provider': job.get('provider'), 'profile': job.get('profile'), 'mode': job.get('mode')}


def get_job_result(config: KnowledgeConfig, job_id: str) -> dict[str, Any]:
    state = load_llm_job_state(config)
    job = state.get('jobs', {}).get(job_id)
    if not job:
        raise ValueError(f'Job not found: {job_id}')
    return {'job_id': job_id, 'status': job.get('status'), 'result': job.get('result'), 'message': job.get('message')}


# Optional provider backends

def provider_disabled(*, task_name: str, payload: dict[str, Any], profile: dict[str, Any], provider_config: dict[str, Any], blocking: bool) -> dict[str, Any]:
    return {'status': 'unavailable', 'message': 'Provider is disabled.', 'result': None}


def provider_mock_overseer(*, task_name: str, payload: dict[str, Any], profile: dict[str, Any], provider_config: dict[str, Any], blocking: bool) -> dict[str, Any]:
    profile_id = str(profile.get('id', provider_config.get('profile_id', 'mock-profile')))
    if task_name == 'answer_question':
        deterministic = dict(payload.get('deterministic_result') or {})
        candidates = list(deterministic.get('candidate_pages', []))
        top = candidates[: min(3, len(candidates))]
        answer = _mock_answer_from_candidates(payload.get('question', ''), top)
        result = {
            'answer': answer,
            'citations': _citations_from_candidates(top),
            'candidate_pages': top,
            'gaps': [],
            'work_remaining': [],
            'profile_used': profile_id,
        }
        return {'status': 'completed', 'message': 'Mock overseer synthesized an answer from deterministic candidates.', 'result': result}
    if task_name == 'draft_sync_proposal':
        deterministic = dict(payload.get('deterministic_result') or {})
        drift_items = list(deterministic.get('drift_items', []))
        result = {
            'summary': f'Mock overseer reviewed {len(drift_items)} drift items and suggests manual refinement of generated sync proposals.',
            'proposal_outline': [
                {
                    'page_id': item.get('page_id'),
                    'source_path': item.get('source_path'),
                    'change_type': item.get('status'),
                    'rationale': item.get('message'),
                }
                for item in drift_items[:10]
            ],
            'profile_used': profile_id,
        }
        return {'status': 'completed', 'message': 'Mock overseer drafted a proposal outline.', 'result': result}
    result = {'summary': f'Mock overseer accepted task {task_name}.', 'payload_keys': sorted(payload.keys()), 'profile_used': profile_id}
    return {'status': 'completed', 'message': 'Mock overseer completed the task.', 'result': result}


# Config-driven deterministic handlers

def deterministic_answer_question(*, config: KnowledgeConfig, task_name: str, payload: dict[str, Any], task_config: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get('question', '')).strip()
    limit = int(payload.get('limit', 8))
    candidates = [asdict(item) for item in search_pages(config, question, limit=limit)]
    navigation = suggest_navigation(config, question, limit=min(limit, 5))
    evidence = _build_evidence(config, candidates, question)
    base = {
        'task_name': task_name,
        'subject': question,
        'candidate_pages': candidates,
        'navigation': navigation,
        'evidence': evidence,
        'citations': _citations_from_candidates(candidates[:3]),
        'gaps': [],
        'work_remaining': [],
        'suggested_actions': _suggested_actions_from_navigation(navigation),
    }
    if not candidates:
        base.update({
            'outcome': 'deterministic_partial',
            'answer': None,
            'gaps': ['No matching pages were found in deterministic retrieval.'],
            'work_remaining': ['Broaden the query.', 'Inspect source material directly.', 'Seed missing current-state pages or manifests.'],
        })
        return base
    complete = _looks_deterministically_complete(candidates)
    if complete:
        top = candidates[0]
        base.update({
            'outcome': 'deterministic_complete',
            'answer': f"Most relevant current-state page: {top.get('title')} [{top.get('page_id')}]. Deterministic retrieval found a strong leading match.",
            'work_remaining': ['Verify the cited section snippets in the top page.', 'Inspect related pages if you need broader context.'],
        })
    else:
        titles = ', '.join(item.get('title', '<unknown>') for item in candidates[:3])
        base.update({
            'outcome': 'deterministic_partial',
            'answer': f'Deterministic retrieval found likely relevant pages: {titles}. No model synthesis was used.',
            'gaps': ['A human or caller still needs to read the top candidate pages for synthesis.'],
            'work_remaining': ['Read the top candidate pages.', 'Inspect the evidence snippets and related pages.', 'Run a richer optional provider later if synthesis is needed.'],
        })
    return base


def deterministic_answer_titles_only(*, config: KnowledgeConfig, task_name: str, payload: dict[str, Any], task_config: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get('question', '')).strip()
    limit = int(payload.get('limit', 5))
    candidates = [asdict(item) for item in search_pages(config, question, limit=limit)]
    return {
        'task_name': task_name,
        'subject': question,
        'outcome': 'deterministic_partial',
        'answer': 'Titles-only deterministic handler was used.',
        'candidate_pages': candidates,
        'navigation': {'matched_routes': [], 'search_hits': candidates, 'fallback_actions': []},
        'evidence': [],
        'citations': _citations_from_candidates(candidates[:2]),
        'gaps': ['Titles-only mode does not inspect sections or source hints.'],
        'work_remaining': ['Open the candidate pages directly.'],
        'suggested_actions': ['search_pages'],
    }


def deterministic_draft_sync_proposal(*, config: KnowledgeConfig, task_name: str, payload: dict[str, Any], task_config: dict[str, Any]) -> dict[str, Any]:
    page_id = payload.get('page_id')
    drift = [asdict(item) for item in scan_drift(config)]
    if page_id:
        drift = [item for item in drift if item['page_id'] == page_id]
    if not drift:
        return {
            'task_name': task_name,
            'subject': page_id or '<all>',
            'outcome': 'deterministic_complete',
            'answer': 'No drift items require a sync proposal.',
            'drift_items': [],
            'proposal_paths': [],
            'gaps': [],
            'work_remaining': [],
        }
    generated = [str(path.relative_to(config.root)) for path in generate_sync_proposals(config)]
    return {
        'task_name': task_name,
        'subject': page_id or '<all>',
        'outcome': 'deterministic_complete',
        'answer': f'Deterministic sync-review proposals were generated for {len(drift)} drift items.',
        'drift_items': drift,
        'proposal_paths': generated,
        'gaps': [],
        'work_remaining': ['Review the generated proposal files.', 'Apply or refine patches as needed.'],
        'suggested_actions': ['generate_sync_proposals', 'record_sync'],
    }


def deterministic_bootstrap_project_knowledge(*, config: KnowledgeConfig, task_name: str, payload: dict[str, Any], task_config: dict[str, Any]) -> dict[str, Any]:
    manifest_name = payload.get('manifest')
    manifest_paths = sorted(config.import_manifest_root.glob('*.yml')) + sorted(config.import_manifest_root.glob('*.yaml'))
    selected_manifest = None
    if manifest_name:
        selected_manifest = (config.root / str(manifest_name)).resolve()
        manifests = [selected_manifest] if selected_manifest.exists() else []
    else:
        manifests = manifest_paths
    source_root = config.knowledge_root / 'source_material'
    source_files = [p for p in source_root.rglob('*') if p.is_file()] if source_root.exists() else []
    by_suffix: dict[str, int] = {}
    for path in source_files:
        suffix = path.suffix.lower() or '<no_suffix>'
        by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
    page_count = sum(1 for _ in config.pages_root.rglob('*.md')) if config.pages_root.exists() else 0
    manifest_items = []
    for manifest in manifests:
        data = load_yaml_file(manifest, {'items': []})
        items = data.get('items', []) if isinstance(data, dict) else []
        manifest_items.append({'path': str(manifest.relative_to(config.root)), 'item_count': len(items) if isinstance(items, list) else 0})
    return {
        'task_name': task_name,
        'subject': selected_manifest.name if selected_manifest else '<all-manifests>',
        'outcome': 'deterministic_complete',
        'answer': 'Deterministic bootstrap inspection completed without model assistance.',
        'inventory': {
            'source_root': str(source_root.relative_to(config.root)),
            'source_file_count': len(source_files),
            'source_counts_by_suffix': dict(sorted(by_suffix.items())),
            'manifests': manifest_items,
            'existing_page_count': page_count,
        },
        'gaps': ['No semantic clustering or concept extraction was performed in deterministic mode.'],
        'work_remaining': ['Review the source inventory.', 'Update or create import manifests.', 'Seed pages from manifest.', 'Use optional providers later for deeper repo interrogation.'],
        'suggested_actions': ['seed_from_manifest', 'scaffold_page', 'search_pages'],
    }


def _run_task(config: KnowledgeConfig, task_name: str, payload: dict[str, Any], *, allow_llm: bool | None, mode: str | None) -> dict[str, Any]:
    task = _resolve_task_config(config, task_name, allow_llm=allow_llm, mode=mode)
    handler = load_handler(str(task['deterministic_handler']))
    deterministic_result = handler(config=config, task_name=task_name, payload=payload, task_config=task)
    if not isinstance(deterministic_result, dict):
        raise ValueError('Deterministic handler returned invalid payload')
    deterministic_result.setdefault('execution', {
        'path': 'deterministic_first',
        'mode': task['mode'],
        'used_llm': False,
        'provider': task['provider'],
        'profile': task['profile'],
    })
    if not task['use_llm']:
        return deterministic_result
    provider_payload = {**payload, 'deterministic_result': deterministic_result}
    if task['mode'] == 'async':
        return submit_profile_job(config, task_name, provider_payload, mode='async', allow_llm=True)
    provider_result = _call_provider(config, task, task_name=task_name, payload=provider_payload)
    return _merge_provider_response(deterministic_result, provider_result)


def _resolve_task_config(config: KnowledgeConfig, task_name: str, *, allow_llm: bool | None, mode: str | None) -> dict[str, Any]:
    tasks = load_execution_registry(config) or {}
    record = {**DEFAULT_TASKS.get(task_name, {}), **tasks.get(task_name, {})}
    if 'deterministic_handler' not in record:
        raise ValueError(f'No execution task is configured for {task_name}')
    provider = str(record.get('provider', config.llm_default_provider or 'disabled'))
    profile = str(record.get('profile', task_name))
    effective_mode = mode or str(record.get('mode', config.llm_default_mode or 'blocking'))
    allow_by_policy = bool(record.get('allow_llm', False))
    use_llm = config.llm_enabled and provider != 'disabled' and (allow_by_policy if allow_llm is None else allow_llm)
    return {**record, 'provider': provider, 'profile': profile, 'mode': effective_mode, 'use_llm': use_llm}


def _call_provider(config: KnowledgeConfig, policy: dict[str, Any], *, task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    registry = load_llm_provider_registry(config)
    handler, defaults = resolve_registry_handler(registry, policy['provider'])
    profiles = load_llm_profiles(config)
    profile = dict(profiles.get(policy['profile'], {}))
    profile['id'] = policy['profile']
    provider_config = {**defaults, **registry.get(policy['provider'], {})}
    blocking = policy['mode'] != 'async'
    result = handler(task_name=task_name, payload=payload, profile=profile, provider_config=provider_config, blocking=blocking)
    if not isinstance(result, dict):
        raise ValueError('Optional provider returned invalid result payload')
    if not blocking and 'job_id' not in result:
        result['job_id'] = _make_job_id(task_name, payload)
    return result


def _merge_provider_response(base: dict[str, Any], provider_result: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    payload = dict(provider_result.get('result') or {})
    execution = dict(result.get('execution', {}))
    execution['path'] = 'deterministic_then_optional_provider'
    execution['used_llm'] = provider_result.get('status') == 'completed'
    result['execution'] = execution
    if provider_result.get('status') == 'completed':
        result.update({
            'outcome': 'llm_assisted_complete',
            'answer': payload.get('answer') or payload.get('summary') or result.get('answer'),
            'citations': payload.get('citations', result.get('citations', [])),
            'candidate_pages': payload.get('candidate_pages', result.get('candidate_pages', [])),
            'gaps': payload.get('gaps', result.get('gaps', [])),
            'work_remaining': payload.get('work_remaining', result.get('work_remaining', [])),
            'provider_result': payload,
            'message': provider_result.get('message'),
        })
    else:
        result.update({
            'outcome': result.get('outcome', 'deterministic_partial'),
            'message': provider_result.get('message'),
        })
    return result


def _build_evidence(config: KnowledgeConfig, candidates: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    query_terms = {term.lower() for term in question.replace('-', ' ').split() if term.strip()}
    evidence: list[dict[str, Any]] = []
    for candidate in candidates[:3]:
        page = load_page_by_id(config.pages_root, config.meta_root, str(candidate.get('page_id', '')))
        if page is None:
            evidence.append({'page_id': candidate.get('page_id'), 'title': candidate.get('title'), 'path': candidate.get('path'), 'section': None, 'snippet': candidate.get('snippet')})
            continue
        matched_sections = []
        for section in page.sections:
            hay = f"{section.title}\n{section.body}".lower()
            if query_terms and not any(term in hay for term in query_terms):
                continue
            matched_sections.append({'title': section.title, 'snippet': _clip(section.body)})
            if len(matched_sections) >= 2:
                break
        if not matched_sections and page.sections:
            matched_sections.append({'title': page.sections[0].title, 'snippet': _clip(page.sections[0].body)})
        for item in matched_sections:
            evidence.append({'page_id': page.page_id, 'title': page.title, 'path': str(page.content_path.relative_to(config.root)), 'section': item['title'], 'snippet': item['snippet']})
    return evidence


def _looks_deterministically_complete(candidates: list[dict[str, Any]]) -> bool:
    if not candidates:
        return False
    top_score = float(candidates[0].get('score', 0))
    if len(candidates) != 1:
        return False
    return top_score >= 20.0


def _suggested_actions_from_navigation(navigation: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for route in navigation.get('matched_routes', []) or []:
        for action_id in route.get('deterministic_actions', []) or []:
            if action_id not in actions:
                actions.append(str(action_id))
    for fallback in navigation.get('fallback_actions', []) or []:
        action_id = str(fallback.get('action_id', '')).strip()
        if action_id and action_id not in actions:
            actions.append(action_id)
    return actions


def _citations_from_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{'page_id': item.get('page_id'), 'title': item.get('title'), 'path': item.get('path')} for item in candidates]


def _mock_answer_from_candidates(question: str, candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return 'No candidate pages were available.'
    titles = ', '.join(str(item.get('title')) for item in candidates)
    return f"Mock overseer considered the question '{question}' and selected these candidate pages: {titles}. Read the cited pages for the definitive current-state details."


def _make_job_id(task_name: str, payload: dict[str, Any]) -> str:
    seed = dump_yaml({'task_name': task_name, 'payload': payload, 'at': now_utc().isoformat()})
    return f"job-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"


def _clip(text: str, limit: int = 220) -> str:
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + '...'
