"""Apply the privacy guard's deterministic text transform to tracked files.

Dry-run by default. This mechanical migration never follows symlinks, edits
untracked runtime files, or prints the values it replaces.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from privacy_guard import sanitize_text, _load_terms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()).resolve()
    _load_terms(root)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).split(b'\0')
    changed = 0
    for raw in names:
        if not raw:
            continue
        name = raw.decode('utf-8')
        file = root / name
        if file.is_symlink() or not file.is_file():
            continue
        if not file.resolve().is_relative_to(root):
            raise ValueError('Tracked path escapes repository')
        before = file.read_bytes()
        if b'\0' in before:
            continue
        try:
            text = before.decode('utf-8')
        except UnicodeError:
            continue
        after = sanitize_text(text, path=name).encode('utf-8')
        if after != before:
            changed += 1
            if args.write:
                file.write_bytes(after)
    print(f'{changed} tracked text files ' + ('redacted' if args.write else 'would change'))


if __name__ == '__main__':
    main()
