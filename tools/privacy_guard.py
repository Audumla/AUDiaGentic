"""Scan immutable Git content for private identifiers; redact without logging values.

Synthetic identifiers have explicit reserved shapes, never directory exemptions.
Optional AUDIAGENTIC_PRIVATE_TERMS is comma/newline separated. CLI local terms
come from an ignored, untracked .audiagentic/privacy/terms.txt, one per line.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

_LOCAL_TERMS: tuple[str, ...] = ()
_SEP = r"(?:\\+|/)"
_DRIVE = r"(?<![A-Za-z0-9])[A-Za-z]:" + _SEP
_DEV = r"(?:development|dev)" + _SEP + r"projects|workspaces?|projects"
_PATHS = (
    ("personal-path", re.compile(_DRIVE + r"Users" + _SEP + r"[^\\/\s\"'<>`{}\[\];,()]+", re.I), "{user-home}"),
    ("development-path", re.compile(_DRIVE + r"(?:" + _DEV + r")(?=[\\/]|$)", re.I), "{dev-root}"),
    ("personal-path", re.compile(r"(?<![A-Za-z0-9_])(?:/mnt/[a-z]/Users|/home|/Users)/[^/\s\"'<>`{}\[\];,()]+", re.I), "{user-home}"),
    ("development-path", re.compile(r"(?<![A-Za-z0-9_])/(?:mnt/[a-z]/(?:development/projects|dev/projects|workspaces?|projects)|workspaces?)(?=/|$)", re.I), "{dev-root}"),
)
_UUID_BODY = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
_UUID = re.compile(r"(?<![A-Za-z0-9])" + _UUID_BODY + r"(?![A-Za-z0-9])", re.I)
_SYNTH_UUID = re.compile(r"00000000-0000-4000-8000-[0-9a-f]{12}$", re.I)
_PROJECT = re.compile(r"(?<![A-Za-z0-9])g-p-([0-9a-f]{32})(?![A-Za-z0-9])", re.I)
_CHAT = re.compile(r"/c/(?P<id>" + _UUID_BODY + r"|[0-9a-f]{12,})(?![A-Za-z0-9-])", re.I)
_OPAQUE = re.compile(r"(?<![A-Za-z0-9_])(?P<kind>req|ses)_(?:(?P<project>[A-Za-z][A-Za-z0-9_]*?)_)?(?P<id>[0-9a-f]{12,})(?![A-Za-z0-9_])", re.I)
_IP = re.compile(r"(?<![A-Za-z0-9_.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![A-Za-z0-9_.])")
_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in ((10 << 24, 8), ((172 << 24) | (16 << 16), 12),
                                                   ((192 << 24) | (168 << 16), 16)))
_URL = re.compile(r"https?://(?:chatgpt\.com|chat\.openai\.com)/[^\s<>\"'`()\[\]{}]+", re.I)


def _hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode('utf-8', 'surrogatepass')).hexdigest()[:length]


def _terms() -> tuple[str, ...]:
    return tuple(sorted(set(_LOCAL_TERMS + tuple(t.strip() for t in
                       re.split(r"[,\n]", os.environ.get('AUDIAGENTIC_PRIVATE_TERMS', '')) if t.strip())), key=len, reverse=True))


def _private_ip(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(address in network for network in _NETWORKS)


def _matches(text: str):
    for category, pattern, _ in _PATHS:
        for match in pattern.finditer(text):
            yield match.start(), category
    for match in _IP.finditer(text):
        if _private_ip(match.group()):
            yield match.start(), 'private-ipv4'
    for match in _PROJECT.finditer(text):
        if not match[1].lower().startswith('0' * 16):
            yield match.start(), 'gpt-project-id'
    for match in _CHAT.finditer(text):
        if not _SYNTH_UUID.fullmatch(match['id']):
            yield match.start(), 'gpt-chat-id'
    for match in _UUID.finditer(text):
        if not _SYNTH_UUID.fullmatch(match.group()):
            yield match.start(), 'opaque-uuid'
    for match in _OPAQUE.finditer(text):
        if (match['project'] or '').lower() != 'example':
            yield match.start(), 'request-id' if match['kind'].lower() == 'req' else 'session-id'
    for term in _terms():
        for match in re.finditer(re.escape(term), text, re.I):
            yield match.start(), 'custom-private-term'


def findings(text: str) -> list[tuple[int, str]]:
    """Return unique (one-based line, category) pairs, never matched values."""
    return sorted({(text.count('\n', 0, pos) + 1, category) for pos, category in _matches(text)})


def sanitize_text(text: str, *, path: str = '') -> str:
    """Deterministic redaction preserving code/JSON/YAML quoting and ID syntax."""
    docs = path.replace('\\', '/').casefold().startswith('docs/') or Path(path).suffix.lower() in {'.md', '.mdx', '.rst', '.txt', '.adoc'}
    if docs:
        def url(match):
            value = match.group()
            if _CHAT.search(value):
                return '{gpt-chat-url}'
            if _PROJECT.search(value):
                return '{gpt-project-url}'
            return value
        text = _URL.sub(url, text)
    for _, pattern, replacement in _PATHS:
        def machine_path(match):
            if docs:
                return replacement
            suffix = 'example-home' if replacement == '{user-home}' else 'example-dev-root'
            if match.group().startswith('/'):
                return '/' + suffix
            separator = re.search(r'\\+|/', match.group()).group()
            return 'C:' + separator + suffix
        text = pattern.sub(machine_path, text)
    # Keep the useful project suffix, with the original slash/escape style.
    text = re.sub(r"(\{dev-root\}|C:(?:\\+|/)example-dev-root|/example-dev-root)(?P<s>\\+|/)(?:AUDia(?P=s))?AUDiaGentic(?=[\\/]|$|[\s\"'])",
                  lambda m: m[1] + m['s'] + 'audiagentic', text, flags=re.I)
    text = _PROJECT.sub(lambda m: m.group() if m[1].lower().startswith('0' * 16)
                        else 'g-p-' + '0' * 16 + _hash(m[1].lower()), text)
    def chat_id(match):
        value = match['id'].lower()
        if _SYNTH_UUID.fullmatch(value):
            return match.group()
        if _UUID.fullmatch(value):
            return '/c/00000000-0000-4000-8000-' + _hash(value, 12)
        return '/c/example-' + _hash(value)
    text = _CHAT.sub(chat_id, text)
    text = _UUID.sub(lambda m: m.group() if _SYNTH_UUID.fullmatch(m.group())
                     else '00000000-0000-4000-8000-' + _hash(m.group().lower(), 12), text)
    text = _OPAQUE.sub(lambda m: m.group() if (m['project'] or '').lower() == 'example'
                       else m['kind'].lower() + '_example_' + _hash(m.group(), len(m['id'])), text)
    def ip(match):
        if not _private_ip(match.group()):
            return match.group()
        return '{dev-host}' if docs else '192.0.2.' + str(1 + int(_hash(match.group(), 8), 16) % 254)
    text = _IP.sub(ip, text)
    for term in _terms():
        text = re.sub(re.escape(term), lambda m: '{dev-host}' if docs else 'host.example.test', text, flags=re.I)
    return text


class GuardError(Exception):
    pass


def _git(root: Path, *args: str, allow: bool = False) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if result.returncode and not allow:
        raise GuardError('git-error')
    return result.stdout if result.returncode == 0 else b''


def _display(raw: bytes) -> str:
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return '<non-utf8-path-' + hashlib.sha256(raw).hexdigest()[:16] + '>'
    text = sanitize_text(text, path='filename.py')
    return text.encode('unicode_escape').decode('ascii').replace(':', '\\x3a')


def _blob_findings(raw: bytes, allowed_binary: bool = False) -> list[tuple[int, str]]:
    binary_hits = []
    # Inspect embedded ASCII and both UTF-16 byte orders even for approved assets.
    for encoding in ('latin-1', 'utf-16-le', 'utf-16-be'):
        binary_hits += findings(raw.decode(encoding, errors='ignore'))
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return sorted(set(binary_hits + ([] if allowed_binary else [(0, 'unscannable-encoding')])))
    hits = findings(text) + binary_hits
    if '\0' in text and not allowed_binary:
        hits.append((0, 'unscannable-binary'))
    return sorted(set(hits))


def _binary_manifest() -> dict[str, str]:
    file = Path(__file__).with_name('privacy_binary_allow.json')
    if not file.exists():
        return {}
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or any(not isinstance(p, str) or not isinstance(d, str)
                                             or not re.fullmatch(r'[0-9a-f]{64}', d)
                                             for p, d in data.items()):
            raise ValueError
        return data
    except (ValueError, OSError, UnicodeError):
        raise GuardError('invalid-binary-manifest') from None


def _batch_blobs(root: Path, oids: set[bytes]) -> dict[bytes, bytes]:
    if not oids:
        return {}
    result = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch'],
                            input=b'\n'.join(sorted(oids)) + b'\n', capture_output=True)
    if result.returncode:
        raise GuardError('git-error')
    stream = io.BytesIO(result.stdout)
    cache = {}
    for oid in sorted(oids):
        header = stream.readline().split()
        if len(header) != 3 or header[0] != oid or header[1] != b'blob':
            raise GuardError('invalid-git-blob')
        raw = stream.read(int(header[2]))
        if len(raw) != int(header[2]) or stream.read(1) != b'\n':
            raise GuardError('invalid-git-blob')
        cache[oid] = raw
    return cache


def _index(root: Path, staged: bool):
    changed = None
    if staged:
        changed = set(_git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z').split(b'\0'))
    for record in _git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, oid, stage = meta.split()
        if stage != b'0':
            raise GuardError('unmerged-index')
        if changed is None or path in changed:
            yield path, mode, oid


def _tree(root: Path, ref: str):
    for record in _git(root, 'ls-tree', '-r', '-z', ref).split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            mode, kind, oid = meta.split()
            yield path, mode, oid


def _load_terms(root: Path) -> None:
    global _LOCAL_TERMS
    _LOCAL_TERMS = ()
    root = root.resolve(strict=True)
    relative = '.audiagentic/privacy/terms.txt'
    file = root / relative
    if any(p.is_symlink() for p in (root / '.audiagentic', file.parent, file)):
        raise GuardError('private-terms-symlink')
    if not file.resolve().is_relative_to(root):
        raise GuardError('private-terms-outside-root')
    if file.exists():
        if _git(root, 'ls-files', '--', relative) or not _git(root, 'check-ignore', '--', relative, allow=True):
            raise GuardError('private-terms-must-be-ignored')
        try:
            _LOCAL_TERMS = tuple(t.strip() for t in file.read_text(encoding='utf-8').splitlines()
                                 if t.strip() and not t.lstrip().startswith('#'))
        except (OSError, UnicodeError):
            raise GuardError('invalid-private-terms') from None


def _install_hook(root: Path) -> None:
    configured = subprocess.run(['git', '-C', str(root), 'config', '--get-all', 'core.hooksPath'], capture_output=True)
    if configured.returncode == 0:
        raise GuardError('existing-hook-configuration')
    hook = Path(os.fsdecode(_git(root, 'rev-parse', '--git-path', 'hooks/pre-commit').strip()))
    if not hook.is_absolute():
        hook = root / hook
    if hook.exists() or hook.is_symlink():
        raise GuardError('existing-pre-commit-hook')
    hook.parent.mkdir(parents=True, exist_ok=True)
    script = '#!/bin/sh\nexec python ' + shlex.quote(str(root / 'tools/privacy_guard.py')) + ' --staged\n'
    try:
        with hook.open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(script)
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError:
        raise GuardError('hook-install-failed') from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GuardError('invalid-arguments')


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--all', action='store_true')
        group.add_argument('--staged', action='store_true')
        group.add_argument('--base')
        group.add_argument('--install-hook', action='store_true')
        args = parser.parse_args(argv)
        bare = _git(Path.cwd(), 'rev-parse', '--is-bare-repository').strip() == b'true'
        root = Path(os.fsdecode(_git(Path.cwd(), 'rev-parse', '--absolute-git-dir' if bare else '--show-toplevel').strip()))
        _load_terms(root)
        if args.install_hook:
            _install_hook(root)
            return 0
        records = []
        if args.base is not None:
            if not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', args.base):
                raise GuardError('base-must-be-immutable-sha')
            if _git(root, 'cat-file', '-t', args.base).strip() != b'commit':
                raise GuardError('base-must-be-commit')
            forkpoint = _git(root, 'merge-base', args.base, 'HEAD', allow=True).strip()
            if not re.fullmatch(rb'[0-9a-f]{40}|[0-9a-f]{64}', forkpoint):
                raise GuardError('base-must-share-history')
            commits = _git(root, 'rev-list', forkpoint.decode('ascii') + '..HEAD').decode('ascii').splitlines()
            # Full HEAD is mandatory even for an empty range.
            records.extend(_tree(root, 'HEAD'))
            for commit in commits:
                records.extend(_tree(root, commit))
                message = _git(root, 'cat-file', 'commit', commit).split(b'\n\n', 1)[1]
                for line, category in _blob_findings(message):
                    print(f'<commit-message>:{line}: {category}')
                    records.append((b'<message-finding>', b'finding', b''))
        else:
            if bare and args.staged:
                raise GuardError('bare-repository-has-no-index')
            records.extend(_tree(root, 'HEAD') if bare else _index(root, args.staged))
        manifest = _binary_manifest()
        blobs = _batch_blobs(root, {oid for _, mode, oid in records if mode not in (b'finding', b'160000')})
        failed = False
        seen = set()
        for path, mode, oid in records:
            if mode == b'finding':
                failed = True
                continue
            if (path, mode, oid) in seen:
                continue
            seen.add((path, mode, oid))
            try:
                path_text = path.decode('utf-8')
                hits = [(0, category) for _, category in findings(path_text)]
            except UnicodeDecodeError:
                hits = [(0, 'unscannable-filename')]
            if mode == b'160000':
                hits.append((0, 'unscannable-submodule'))
            else:
                raw = blobs[oid]
                digest = hashlib.sha256(raw).hexdigest()
                approved = manifest.get(os.fsdecode(path)) == digest
                hits += _blob_findings(raw, allowed_binary=approved)
            for line, category in sorted(set(hits)):
                print(f'{_display(path)}:{line}: {category}')
                failed = True
        return int(failed)
    except (GuardError, OSError, UnicodeError, ValueError) as error:
        category = str(error) if isinstance(error, GuardError) else 'scan-error'
        print(f'<privacy-guard>:0: {category}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
