"""Privacy patterns and real Git-object coverage, without literal private fixtures."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[3] / 'tools/privacy_guard.py'
SPEC = importlib.util.spec_from_file_location('privacy_guard_under_test', SOURCE)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def opaque(kind='req'):
    return kind + '_' + 'ab' * 16


def personal(slash='\\'):
    return 'H:' + slash + slash.join(('development', 'projects', 'AUDia', 'AUDiaGentic', 'src', 'file.py'))


def address():
    return '.'.join(map(str, (192, 168, 12, 34)))


def real_uuid():
    return '-'.join(('12345678', 'abcd', '4321', '9123', 'abcdef123456'))


def categories(text):
    return {category for _, category in guard.findings(text)}


@pytest.mark.parametrize('text, category', [
    (personal(), 'development-path'),
    ('C:' + '\\' + 'Users' + '\\' + 'person' + '\\' + 'file', 'personal-path'),
    ('/' + 'home/person/file', 'personal-path'),
    ('/' + 'Users/person/file', 'personal-path'),
    ('/' + 'mnt/h/development/projects/repo', 'development-path'),
    (address(), 'private-ipv4'),
    (opaque(), 'request-id'), (opaque('ses'), 'session-id'),
    ('req_project_' + 'ab' * 12, 'request-id'),
    ('g-p-' + 'ab' * 16, 'gpt-project-id'),
    ('/c/' + real_uuid(), 'gpt-chat-id'),
    (real_uuid(), 'opaque-uuid'),
])
def test_sensitive_patterns(text, category):
    assert category in categories(text)
    assert guard.findings('\n' + text)[0][0] == 2


@pytest.mark.parametrize('text', [
    '/tmp/example/file', '/usr/bin/python', 'C:/Windows/System32', 'C:/Program Files/Example',
    '127.0.0.1', '192.0.2.12', '198.51.100.5', '203.0.113.2', '8.8.8.8',
    'v' + '.'.join(map(str, (10, 12, 13, 14))),
    '.'.join(map(str, (10, 12, 13, 14, 15))),
    'req_example_' + 'ab' * 16, 'ses_example_' + 'ab' * 16,
    'g-p-example-' + 'ab' * 16, '/c/example-' + 'ab' * 16,
    'g-p-' + '0' * 16 + 'ab' * 8,
    '00000000-0000-4000-8000-' + 'ab' * 6,
    '/c/chat', '/c/session-1', '/g/g-p-proj1',
])
def test_explicit_synthetic_and_generic_values_allowed(text):
    assert guard.findings(text) == []


def test_sanitizer_stable_distinct_and_idempotent():
    text = ' '.join((opaque(), opaque('ses'), real_uuid(), 'g-p-' + 'ab' * 16,
                     '/c/' + real_uuid(), 'g-p-' + 'cd' * 16))
    sanitized = guard.sanitize_text(text, path='module.py')
    assert guard.findings(sanitized) == []
    assert sanitized == guard.sanitize_text(text, path='module.py')
    assert sanitized == guard.sanitize_text(sanitized, path='module.py')
    projects = guard._PROJECT.findall(sanitized)
    assert len(set(projects)) == 2
    assert all(len(p) == 32 and p.startswith('0' * 16) for p in projects)
    token = sanitized.split()[2]
    assert uuid.UUID(token).version == 4
    assert sanitized.split()[4] == '/c/' + token


@pytest.mark.parametrize('length', [12, 16, 64])
@pytest.mark.parametrize('kind', ['req', 'req_project', 'ses'])
def test_opaque_sanitization_preserves_hex_tail_length(length, kind):
    value = kind + '_' + 'a' * length
    output = guard.sanitize_text(value, path='example.py')
    assert output.startswith(('ses' if kind == 'ses' else 'req') + '_example_')
    assert len(output.rsplit('_', 1)[1]) == length
    assert guard.findings(output) == []
    assert guard.sanitize_text(output, path='example.py') == output


def test_docs_replace_complete_links_and_hosts():
    project = 'https://chatgpt.com/g/g-p-' + 'ab' * 16 + '-title'
    chat = 'https://chatgpt.com/c/' + real_uuid()
    output = guard.sanitize_text(f'[{project}]({project}) {chat} {address()} {personal("/")}', path='guide.md')
    assert '{gpt-project-url}' in output and '{gpt-chat-url}' in output
    assert '{dev-host}' in output and '{dev-root}/audiagentic/src/file.py' in output
    assert not guard.findings(output)


@pytest.mark.parametrize('path', ['docs/releases/LEDGER.ndjson', 'docs/reference/record.json'])
def test_docs_structured_records_use_documentation_redaction(path):
    data = {'host': address(), 'chat': 'https://chatgpt.com/c/' + real_uuid(),
            'project': 'https://chatgpt.com/g/g-p-' + 'ab' * 16 + '-title'}
    output = guard.sanitize_text(json.dumps(data) + '\n', path=path)
    assert json.loads(output) == {'host': '{dev-host}', 'chat': '{gpt-chat-url}', 'project': '{gpt-project-url}'}
    assert not guard.findings(output)


def test_json_escaped_windows_and_code_fstrings():
    encoded = json.dumps({'path': personal(), 'ip': address(), 'id': real_uuid()})
    sanitized = guard.sanitize_text(encoded, path='settings.json')
    data = json.loads(sanitized)
    assert data['path'].startswith('C:\\example-dev-root\\audiagentic\\')
    assert data['ip'].startswith('192.0.2.')
    assert uuid.UUID(data['id'])
    code = 'value = f"' + personal('/') + '"'
    result = guard.sanitize_text(code, path='example.py')
    compile(result, '<fixture>', 'exec')
    assert '{' not in result and 'C:/example-dev-root/audiagentic/' in result


def test_optional_custom_terms(monkeypatch):
    term = 'private' + 'personmarker'
    monkeypatch.setenv('AUDIAGENTIC_PRIVATE_TERMS', term)
    assert categories(term) == {'custom-private-term'}
    output = guard.sanitize_text(term, path='example.py')
    assert output == 'host.example.test'
    assert guard.sanitize_text(term, path='guide.md') == '{dev-host}'
    assert guard.findings(output) == []


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Example')
    git(tmp_path, 'config', 'user.email', 'example@example.invalid')
    git(tmp_path, 'config', 'core.autocrlf', 'false')
    return tmp_path


def commit(root, message='fixture'):
    git(root, 'add', '.')
    git(root, 'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


def cli(root, *args, scanner=SOURCE):
    return subprocess.run([sys.executable, str(scanner), *args], cwd=root, capture_output=True, text=True)


def test_all_and_staged_read_index_not_worktree(repo):
    file = repo / 'example.txt'
    file.write_text('safe', encoding='utf-8')
    commit(repo)
    file.write_text(opaque(), encoding='utf-8')
    assert cli(repo, '--all').returncode == 0
    git(repo, 'add', 'example.txt')
    file.write_text('safe again', encoding='utf-8')
    for mode in ('--all', '--staged'):
        result = cli(repo, mode)
        assert result.returncode == 1
        assert 'request-id' in result.stdout and opaque() not in result.stdout + result.stderr
    (repo / 'untracked.txt').write_text(opaque('ses'), encoding='utf-8')
    git(repo, 'reset', '-q', 'HEAD', '--', 'example.txt')
    assert cli(repo, '--all').returncode == 0


def test_staged_only_changed_index_entries(repo):
    (repo / 'existing.txt').write_text(opaque(), encoding='utf-8')
    commit(repo)
    (repo / 'new.txt').write_text('safe', encoding='utf-8')
    git(repo, 'add', 'new.txt')
    assert cli(repo, '--staged').returncode == 0
    assert cli(repo, '--all').returncode == 1


def test_base_scans_intermediate_trees_and_messages(repo):
    file = repo / 'example.txt'
    file.write_text('safe', encoding='utf-8')
    base = commit(repo)
    file.write_text(opaque(), encoding='utf-8')
    commit(repo, opaque('ses'))
    file.write_text('safe', encoding='utf-8')
    commit(repo)
    result = cli(repo, '--base', base)
    assert result.returncode == 1
    assert 'request-id' in result.stdout and 'session-id' in result.stdout
    assert '<commit-message>' in result.stdout
    assert opaque() not in result.stdout + result.stderr
    assert opaque('ses') not in result.stdout + result.stderr


def test_base_always_scans_head_and_rejects_names_and_unrelated_history(repo):
    (repo / 'example.txt').write_text(opaque(), encoding='utf-8')
    head = commit(repo)
    assert cli(repo, '--base', head).returncode == 1
    result = cli(repo, '--base', opaque())
    assert result.returncode == 2 and opaque() not in result.stdout + result.stderr
    git(repo, 'checkout', '--orphan', 'separate')
    (repo / 'example.txt').write_text('safe', encoding='utf-8')
    commit(repo)
    assert 'base-must-share-history' in cli(repo, '--base', head).stdout


def test_diverged_base_scans_all_feature_commits_from_forkpoint(repo):
    file = repo / 'example.txt'
    file.write_text('safe', encoding='utf-8')
    forkpoint = commit(repo)
    git(repo, 'checkout', '-qb', 'feature')
    file.write_text(opaque(), encoding='utf-8')
    commit(repo, opaque('ses'))
    file.write_text('safe again', encoding='utf-8')
    feature = commit(repo)
    git(repo, 'checkout', '-qb', 'advanced-base', forkpoint)
    (repo / 'base.txt').write_text('independent base advancement', encoding='utf-8')
    base = commit(repo)
    git(repo, 'checkout', '--detach', feature)
    result = cli(repo, '--base', base)
    assert result.returncode == 1
    assert 'request-id' in result.stdout and 'session-id' in result.stdout
    assert 'base-must-share-history' not in result.stdout
    assert opaque() not in result.stdout + result.stderr


def test_nonutf8_and_nul_fail_closed_and_scan_embedded_values():
    for raw in (b'\xff' + opaque().encode(), opaque().encode('utf-16-le')):
        hits = guard._blob_findings(raw)
        assert any(category == 'request-id' for _, category in hits)
        assert any(category.startswith('unscannable-') for _, category in hits)
        assert any(category == 'request-id' for _, category in guard._blob_findings(raw, allowed_binary=True))


def test_binary_manifest_binds_exact_path_and_digest(repo):
    tools = repo / 'tools'; tools.mkdir()
    scanner = tools / 'privacy_guard.py'; scanner.write_bytes(SOURCE.read_bytes())
    raw = b'\x89PNG\r\n\x1a\n' + b'\xff\0example'
    asset = repo / 'icon.png'; asset.write_bytes(raw)
    manifest = tools / 'privacy_binary_allow.json'
    manifest.write_text(json.dumps({'icon.png': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
    git(repo, 'add', 'icon.png')
    assert cli(repo, '--all', scanner=scanner).returncode == 0
    asset.write_bytes(raw + b'changed'); git(repo, 'add', 'icon.png')
    assert cli(repo, '--all', scanner=scanner).returncode == 1
    asset.write_bytes(raw); asset.rename(repo / 'other.png')
    git(repo, 'add', '-A')
    assert cli(repo, '--all', scanner=scanner).returncode == 1


def test_output_redacts_sensitive_filename_and_controls(repo):
    name = opaque() + '.txt'
    (repo / name).write_text(opaque('ses'), encoding='utf-8')
    git(repo, 'add', name)
    result = cli(repo, '--all')
    assert result.returncode == 1
    assert name not in result.stdout and opaque('ses') not in result.stdout + result.stderr
    assert 'request-id' in result.stdout and 'session-id' in result.stdout
    assert '\n' not in guard._display(b'fake\nname.txt')


def test_hook_refuses_existing_configuration_and_hook(repo):
    git(repo, 'config', 'core.hooksPath', '.existing-hooks')
    assert cli(repo, '--install-hook').returncode == 2
    assert git(repo, 'config', 'core.hooksPath') == '.existing-hooks'
    git(repo, 'config', '--unset', 'core.hooksPath')
    hook = repo / '.git/hooks/pre-commit'
    hook.write_text('existing hook', encoding='utf-8')
    assert cli(repo, '--install-hook').returncode == 2
    assert hook.read_text() == 'existing hook'


def test_ignored_local_terms_are_optional_and_enforced(repo):
    term = 'private' + 'localmarker'
    (repo / '.gitignore').write_text('/.audiagentic/\n', encoding='utf-8')
    local = repo / '.audiagentic/privacy/terms.txt'; local.parent.mkdir(parents=True)
    local.write_text(term, encoding='utf-8')
    (repo / 'example.txt').write_text(term, encoding='utf-8')
    git(repo, 'add', '.gitignore', 'example.txt')
    result = cli(repo, '--all')
    assert result.returncode == 1 and 'custom-private-term' in result.stdout
    assert term not in result.stdout + result.stderr


def test_guard_sources_do_not_exempt_themselves():
    assert guard.findings(SOURCE.read_text(encoding='utf-8')) == []
    assert guard.findings(Path(__file__).read_text(encoding='utf-8')) == []


def test_local_terms_symlink_is_rejected(repo, tmp_path):
    outside = tmp_path / 'outside-terms.txt'
    outside.write_text('private' + 'marker', encoding='utf-8')
    file = repo / '.audiagentic/privacy/terms.txt'
    file.parent.mkdir(parents=True)
    try:
        file.symlink_to(outside)
    except OSError:
        pytest.skip('Symlinks require local OS permission')
    result = cli(repo, '--all')
    assert result.returncode == 2
    assert 'private-terms-symlink' in result.stdout


def test_local_terms_resolved_path_cannot_escape_root(repo, monkeypatch):
    root = repo.resolve()
    file = root / '.audiagentic/privacy/terms.txt'
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        if path == file:
            return root.parent / 'outside-terms.txt'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    with pytest.raises(guard.GuardError, match='private-terms-outside-root'):
        guard._load_terms(root)
