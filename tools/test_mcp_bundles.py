"""Build/install each extracted wheel and exercise isolated stdio MCP sessions.

Requires uv and the MCP SDK in this test runner, not in the source checkout.
Each server gets its own non-system-site-packages virtual environment and a
temporary project. No existing gateway, browser or provider sessions are used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} operation failed: {result.stderr[-3000:]}')
    return result.stdout


def payload(result):
    if result.isError:
        raise AssertionError('MCP returned error: ' + str(result.content))
    if result.structuredContent is not None:
        return result.structuredContent
    for block in result.content:
        if block.type == 'text':
            try:
                return json.loads(block.text)
            except ValueError:
                return block.text
    raise AssertionError('MCP result had no output')


async def protocol(python: Path, manifest: dict, project: Path, errlog) -> dict:
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith('AUDIAGENTIC_') and k not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV')}
    environment['AUDIAGENTIC_REPO_ROOT'] = str(project)
    console = python.parent / (manifest['server'] + ('.exe' if os.name == 'nt' else ''))
    assert console.is_file(), 'Installed console entrypoint missing'
    params = StdioServerParameters(command=str(console), args=[],
                                   env=environment, cwd=str(project))
    async with stdio_client(params, errlog=errlog) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert set(manifest['expected_tools']) <= names, 'Descriptor tools missing from server'
            assert initialized.serverInfo.name == manifest['server'], 'Wrong server identity/configuration'
            checks = ['initialize', 'tools/list', 'descriptor-tools', 'server-identity']
            if manifest['server'] == 'ag-planning':
                item = {'id': 'PKG01', 'plan': 'packaging-proof', 'title': 'Isolated package test',
                        'validation': 'Protocol CRUD round trip.', 'acceptance_criteria': 'Returned item matches.'}
                created = payload(await session.call_tool('plan_create_item', {'item': item}))
                assert created.get('id') == 'PKG01', created
                item_data = payload(await session.call_tool('plan_get_item', {'item_id': 'PKG01'}))
                assert 'PKG01' in json.dumps(item_data), 'Created item unavailable'
                payload(await session.call_tool('plan_update_item', {'item_id': 'PKG01', 'updates': {'title': 'Updated isolated test'}}))
                payload(await session.call_tool('plan_set_state', {'item_id': 'PKG01', 'new_state': 'completed'}))
                assert (project / 'docs/planning/completed/packaging-proof/PKG01.md').exists()
                payload(await session.call_tool('plan_delete_item', {'item_id': 'PKG01'}))
                assert not (project / 'docs/planning/completed/packaging-proof/PKG01.md').exists()
                checks.append('planning-create-read-update-complete-delete')
            if manifest['server'] == 'ag-ledger':
                event = {'change-class': 'code-fix', 'files': ['example.py'],
                         'technical-summary': 'Isolated bundle test.',
                         'user-summary-candidate': 'Validate standalone ledger.', 'status': 'unreleased'}
                recorded = payload(await session.call_tool('record_change_event', {'event': event}))
                assert recorded, 'Ledger event missing'
                summary = payload(await session.call_tool('get_current_summary', {}))
                assert 'standalone ledger' in json.dumps(summary), 'Ledger summary missing recorded event'
                checks.append('ledger-record-sync-summary')
            return {'server': manifest['server'], 'tools': len(names), 'checks': checks, 'passed': True}


def test_bundle(bundle: Path, evidence: Path) -> dict:
    manifest = json.loads((bundle / 'extraction.json').read_text(encoding='utf-8'))
    location = evidence / manifest['server']
    location.mkdir(parents=True, exist_ok=False)
    run('uv', 'build', '--wheel', str(bundle), '--out-dir', str(location / 'dist'))
    wheels = list((location / 'dist').glob('*.whl'))
    assert len(wheels) == 1, 'Expected one wheel'
    run('uv', 'venv', str(location / 'venv'))
    python = location / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    run('uv', 'pip', 'install', '--python', str(python), str(wheels[0]))
    # Verify the application distribution is absent and the entrypoint is
    # imported from this environment, never an editable checkout.
    probe = ('import importlib.metadata as d,importlib.util,json; '
             f's=importlib.util.find_spec({manifest["module"]!r}); '
             'print(json.dumps({"origin":s.origin,"distributions":[x.metadata["Name"] for x in d.distributions()]}))')
    with tempfile.TemporaryDirectory(prefix='ag-mcp-proof-') as temporary:
        project = Path(temporary)
        (project / '.audiagentic').mkdir()
        run('git', 'init', '--quiet', str(project))
        metadata = json.loads(run(str(python), '-I', '-c', probe, cwd=project))
        assert 'audiagentic' not in metadata['distributions'], 'Full application installed'
        assert Path(metadata['origin']).resolve().is_relative_to((location / 'venv').resolve()), 'Source checkout leakage'
        with (location / 'protocol-stderr.log').open('w', encoding='utf-8') as log:
            # stderr is captured by the parent test command; keep JSON evidence
            # compact and never include project contents in the public report.
            result = asyncio.run(asyncio.wait_for(protocol(python, manifest, project, log), timeout=90))
        diagnostics = (location / 'protocol-stderr.log').read_text(encoding='utf-8')
        assert not any(marker in diagnostics for marker in (
            'ModuleNotFoundError', 'Skipping provider descriptor', 'Failed to import lifecycle observer'
        )), 'Unresolved runtime imports in server diagnostics'
    result.update(wheel=wheels[0].name, wheel_bytes=wheels[0].stat().st_size,
                  wheel_sha256=hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
                  module_count=len(manifest['modules']), full_application_installed=False)
    (location / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--server', action='append', default=[])
    args = parser.parse_args()
    results = []
    for bundle in sorted(args.bundles.resolve().iterdir()):
        if not (bundle / 'extraction.json').exists() or (args.server and bundle.name not in args.server):
            continue
        try:
            result = test_bundle(bundle, args.evidence.resolve())
        except Exception as error:
            result = {'server': bundle.name, 'passed': False, 'error_type': type(error).__name__}
            directory = args.evidence.resolve() / bundle.name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        results.append(result)
        print(json.dumps(result), flush=True)
    assert results, 'No bundles selected'
    (args.evidence / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    raise SystemExit(int(any(not r['passed'] for r in results)))


if __name__ == '__main__':
    main()
