"""Standalone bundle boundaries and reproducible provenance."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('extract_mcp', ROOT / 'tools/extract_mcp.py')
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)


def test_discovery_is_descriptor_driven():
    servers = extractor.discover()
    assert 'ag-planning' in servers and 'ag-ledger' in servers
    assert 'git' not in servers and 'github' not in servers
    assert all((ROOT / value['descriptor']).is_file() for value in servers.values())


def test_descriptor_references_include_hooks_not_embedded_examples():
    values = {'hook': 'audiagentic.example.module:handler',
              'nested': ['audiagentic.other.module.Class'],
              'prose': 'For example audiagentic.nonexistent.module is not a configured hook.'}
    assert set(extractor.descriptor_refs(values)) == {'audiagentic.example.module', 'audiagentic.other.module.Class'}


def test_relative_imports_and_package_initializers(tmp_path):
    package = tmp_path / 'src/audiagentic'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('from . import shared\n')
    (package / 'shared.py').write_text('VALUE = 1\n')
    (package / 'entry.py').write_text('from .shared import VALUE\n')
    result = extractor.closure('audiagentic.entry', tmp_path)
    assert set(result) == {'audiagentic', 'audiagentic.entry', 'audiagentic.shared'}


def test_unknown_server_does_not_create_output(tmp_path):
    with pytest.raises(ValueError, match='Unknown MCP'):
        extractor.extract('../unknown', tmp_path)
    assert not list(tmp_path.iterdir())


def test_unresolved_internal_import_fails_closed(tmp_path):
    package = tmp_path / 'src/audiagentic'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    (package / 'entry.py').write_text('import audiagentic.missing\n')
    with pytest.raises(ValueError, match='Unresolved internal Python import'):
        extractor.closure('audiagentic.entry', tmp_path)


def test_bundle_contains_provenance_entrypoint_and_resources(tmp_path):
    manifest = extractor.extract('ag-planning', tmp_path)
    target = tmp_path / 'ag-planning'
    assert manifest['module'] == 'audiagentic.components.planning.planning_mcp'
    assert 'audiagentic.components.planning.items' in manifest['modules']
    assert 'src/audiagentic/components/planning/workflows.yaml' in manifest['files']
    assert not any('/tests/' in name or '/.audiagentic/' in name for name in manifest['files'])
    assert json.loads((target / 'extraction.json').read_text()) == manifest
    assert 'ag-planning=' in (target / 'pyproject.toml').read_text()
    assert not (target / '.git').exists()
    with pytest.raises(ValueError, match='Output exists'):
        extractor.extract('ag-planning', tmp_path)


def test_provenance_is_deterministic(tmp_path):
    first = extractor.extract('ag-ledger', tmp_path / 'one')
    second = extractor.extract('ag-ledger', tmp_path / 'two')
    assert first == second
