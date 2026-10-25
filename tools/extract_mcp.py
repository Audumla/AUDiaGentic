"""Build standalone source bundles from canonical MCP entry points.

Generated distributions vendor the conservative internal import closure; they
are alternatives installed in separate environments, not co-installable plugins.
No source files in the repository are modified by extraction.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from functools import cache, lru_cache
from pathlib import Path

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


def descriptor_refs(value):
    """Yield literal configured references, not examples inside prose/scripts."""
    if isinstance(value, dict):
        for child in value.values():
            yield from descriptor_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from descriptor_refs(child)
    elif isinstance(value, str) and re.fullmatch(r'audiagentic(?:\.[A-Za-z_]\w*)+(?::[A-Za-z_][\w.]*)?', value):
        yield value.split(':', 1)[0]


def discover(root: Path = ROOT) -> dict[str, dict]:
    servers = {}
    for path in sorted((root / 'src/audiagentic/config/components').glob('*.yaml')):
        descriptor = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(descriptor, dict):
            continue
        for server in descriptor.get('mcp-servers', []):
            name, module = server['name'], server['module']
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name) or not module.startswith('audiagentic.'):
                raise ValueError('Unsupported internal MCP declaration')
            if name in servers:
                raise ValueError('Duplicate MCP server name')
            servers[name] = {'module': module, 'descriptor': path.relative_to(root).as_posix(),
                             'tools': server.get('direct-tools', [])}
    return servers


@lru_cache(maxsize=4)
def module_index(root: Path) -> dict[str, Path]:
    result = {}
    for path in sorted((root / 'src/audiagentic').rglob('*.py')):
        parts = list(path.relative_to(root / 'src').with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        result['.'.join(parts)] = path
    return result


@cache
def imports(path: Path, module: str, root: Path) -> set[str]:
    index = module_index(root)
    package = module if path.name == '__init__.py' else module.rpartition('.')[0]
    result = set()
    required = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
            required.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = importlib.util.resolve_name('.' * node.level + base, package)
            result.add(base)
            required.add(base)
            result.update(base + '.' + alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Literal dynamic modules and fully qualified hook names.
            if re.fullmatch(r'audiagentic(?:\.[A-Za-z_]\w*)+', node.value):
                result.add(node.value)
    local = set()
    for name in required:
        if name.startswith('audiagentic.') and name not in index and not any(m.startswith(name + '.') for m in index):
            raise ValueError('Unresolved internal Python import: ' + name)
    for name in result:
        if not name.startswith('audiagentic'):
            continue
        while name and name not in index:
            name = name.rpartition('.')[0]
        if name:
            local.add(name)
    return local


@cache
def closure(entry: str, root: Path = ROOT) -> dict[str, Path]:
    index = module_index(root)
    if entry not in index:
        raise ValueError('MCP module is absent')
    pending, selected = [entry], {}
    while pending:
        module = pending.pop()
        if module in selected:
            continue
        selected[module] = index[module]
        pending.extend(imports(index[module], module, root) - selected.keys())
        parent = module.rpartition('.')[0]
        while parent:
            if parent in index and parent not in selected:
                pending.append(parent)
            parent = parent.rpartition('.')[0]
    return selected


def extract(name: str, output: Path, root: Path = ROOT) -> dict:
    servers = discover(root)
    if name not in servers:
        raise ValueError('Unknown MCP; use --list')
    target = output.resolve() / name
    if target.exists():
        raise ValueError('Output exists; choose a fresh directory')
    if (root / 'src').resolve() in target.parents or target == root.resolve() or '.git' in target.parts:
        raise ValueError('Output overlaps source')
    entry = servers[name]['module']
    selected = dict(closure(entry, root))
    # Shared descriptors contain lazy hooks not expressed as Python imports.
    # Include only descriptors belonging to components in the import closure.
    config = root / 'src/audiagentic/config'
    # Provider and provisioning descriptors contain module:callable references
    # resolved at runtime. Static Python imports alone cannot discover these.
    index = module_index(root)
    for resource in sorted(config.rglob('*.yaml')):
        for reference in descriptor_refs(yaml.safe_load(resource.read_text(encoding='utf-8'))):
            candidate = reference
            while candidate and candidate not in index:
                candidate = candidate.rpartition('.')[0]
            if not candidate or candidate == 'audiagentic':
                raise ValueError('Unresolved configured Python reference: ' + reference)
            selected.update(closure(candidate, root))
    descriptors = list((config / 'components').glob('*.yaml'))
    configs = set()
    while True:
        old_count = len(selected)
        component_prefixes = {'.'.join(m.split('.')[:3]) + '.' for m in selected
                              if m.startswith('audiagentic.components.')}
        for path in descriptors:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                continue
            strings = [v for v in data.values() if isinstance(v, str)]
            strings += [s['module'] for s in data.get('mcp-servers', [])]
            if any(s.startswith(tuple(component_prefixes)) for s in strings) or path == root / servers[name]['descriptor']:
                configs.add(path)
                for value in strings:
                    if value.startswith('audiagentic.'):
                        candidate = value
                        index = module_index(root)
                        while candidate and candidate not in index:
                            candidate = candidate.rpartition('.')[0]
                        if candidate:
                            selected.update(closure(candidate, root))
        if len(selected) == old_count:
            break
    files = set(selected.values())
    # Include schemas/localization/provisioning assets; component descriptor
    # roots are filtered so absent optional components are not advertised.
    for path in config.rglob('*'):
        if not path.is_file() or path.suffix in ('.py', '.pyc'):
            continue
        rel = path.relative_to(config)
        if rel.parts[0] != 'components' or path in configs or len(rel.parts) > 2:
            files.add(path)
    for path in selected.values():
        files.update(p for p in path.parent.iterdir() if p.is_file() and p.suffix in ('.yaml', '.yml', '.json', '.md', '.png'))
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    package_root = root / 'src/audiagentic'
    for pattern in project.get('tool', {}).get('setuptools', {}).get('package-data', {}).get('audiagentic', []):
        for asset in package_root.glob(pattern):
            if not asset.is_file() or asset.suffix in ('.py', '.pyc'):
                continue
            if asset.parent == config / 'components' and asset not in configs:
                continue
            files.add(asset)
    version = project['project']['version']
    target.mkdir(parents=True)
    for source in sorted(files):
        if source.is_symlink():
            raise ValueError('Symlink source is unsupported')
        destination = target / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    distribution = 'audiagentic-mcp-' + name.removeprefix('ag-')
    # Conservative runtime dependencies; browser/ACP/A2A extras are optional
    # capabilities of agent-related MCPs, never the full application package.
    deps = project['project']['dependencies']
    config_text = '[build-system]\nrequires=["setuptools>=67", "wheel"]\nbuild-backend="setuptools.build_meta"\n'
    config_text += f'\n[project]\nname={json.dumps(distribution)}\nversion={json.dumps(version)}\nrequires-python=">=3.10"\ndependencies={json.dumps(deps)}\n'
    config_text += '\n[project.optional-dependencies]\n'
    for extra, requirements in project['project'].get('optional-dependencies', {}).items():
        if extra not in ('dev', 'test', 'mcp'):
            config_text += f'{json.dumps(extra)}={json.dumps(requirements)}\n'
    config_text += f'\n[project.scripts]\n{name}={json.dumps(entry + ":main")}\n'
    config_text += '\n[tool.setuptools.packages.find]\nwhere=["src"]\n\n[tool.setuptools.package-data]\n"audiagentic"=["**/*.yaml", "**/*.yml", "**/*.json", "**/*.md", "**/*.png", "**/*.ts"]\n'
    (target / 'pyproject.toml').write_text(config_text, encoding='utf-8')
    for license_path in root.glob('LICENSE*'):
        if license_path.is_file():
            shutil.copyfile(license_path, target / license_path.name)
    manifest = {'schema': 'mcp-extraction.v1', 'server': name, 'module': entry,
                'distribution': distribution, 'version': version, 'expected_tools': servers[name]['tools'],
                'isolation': 'one bundle per virtual environment; bundles share the audiagentic namespace',
                'modules': sorted(selected), 'files': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    (target / 'extraction.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--server', action='append', default=[])
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if args.list:
        print(json.dumps(discover(), indent=2))
        return
    if not args.output or not (args.all or args.server) or (args.all and args.server):
        parser.error('Use --list or (--all | --server NAME) --output DIRECTORY')
    for name in sorted(discover() if args.all else set(args.server)):
        manifest = extract(name, args.output)
        if args.build:
            result = subprocess.run([sys.executable, '-m', 'build', '--wheel', str(args.output.resolve() / name)],
                                    capture_output=True, text=True)
            if result.returncode:
                (args.output / name / 'build-failure.log').write_text(result.stdout + result.stderr, encoding='utf-8')
                raise RuntimeError('Wheel build failed; see generated build-failure.log')
        print(json.dumps({'server': name, 'modules': len(manifest['modules']), 'files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
