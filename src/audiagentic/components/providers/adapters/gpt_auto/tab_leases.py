"""Durable ownership of physical tabs, never inferred from arbitrary browser tabs."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class TabLeaseStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS tabs (
                target TEXT PRIMARY KEY, session TEXT NOT NULL, url TEXT NOT NULL,
                activity REAL NOT NULL, digest TEXT NOT NULL)''')

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            # sqlite's transaction context commits/rolls back but does not
            # close the handle (observable as locked files on Windows).
            connection.close()

    def observe(self, target: str, session: str, url: str, activity: float, digest: str) -> None:
        with self._connect() as db:
            db.execute('''INSERT INTO tabs VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(target) DO UPDATE SET session=excluded.session,
                url=excluded.url, activity=MAX(tabs.activity, excluded.activity),
                digest=excluded.digest''', (target, session, url, activity, digest))

    def entries(self) -> list[tuple[str, str, str, float, str]]:
        with self._connect() as db:
            return db.execute('SELECT target, session, url, activity, digest FROM tabs').fetchall()

    def forget(self, target: str) -> None:
        with self._connect() as db:
            db.execute('DELETE FROM tabs WHERE target=?', (target,))
