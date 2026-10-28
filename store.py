"""Small SQLite repository. One connection per operation; jobs survive process restarts."""
import json
from pathlib import Path
import sqlite3
import time


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT, kind TEXT, state TEXT, updated REAL);
              CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT);
              CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, project TEXT, candidate TEXT, rating INTEGER, features TEXT);
              CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def interrupt_jobs(self):
        with self.connect() as db:
            for jid, state in db.execute('SELECT id,state FROM jobs').fetchall():
                value = json.loads(state)
                if value['status'] not in ('done', 'error', 'interrupted', 'paused'):
                    value.update(status='interrupted', error='Server stopped. Retry the operation; completed transcript chunks will be reused.')
                    db.execute('UPDATE jobs SET state=? WHERE id=?', (json.dumps(value), jid))

    def create_job(self, jid, project, kind, state):
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', (jid, project, kind, json.dumps(state), time.time()))

    def job(self, jid):
        with self.connect() as db:
            row = db.execute('SELECT state FROM jobs WHERE id=?', (jid,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_job(self, jid, **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM jobs WHERE id=?', (jid,)).fetchone()
            value = json.loads(row[0]); value.update(changes)
            db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?', (json.dumps(value), time.time(), jid))
        return value

    def active(self, pid, kind):
        with self.connect() as db:
            rows = db.execute('SELECT id,state FROM jobs WHERE project=? AND kind=?', (pid, kind)).fetchall()
        return next((jid for jid, state in rows if json.loads(state)['status'] not in ('done', 'error', 'interrupted', 'paused')), None)

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT value FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?)', (key, json.dumps(value)))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))

    def feedback(self, pid, candidate, rating, features):
        with self.connect() as db:
            db.execute('INSERT INTO feedback(project,candidate,rating,features) VALUES(?,?,?,?)', (pid, candidate, rating, json.dumps(features)))

    def preferences(self):
        with self.connect() as db:
            rows = db.execute('SELECT rating,features FROM feedback').fetchall()
        # Explicit bounded linear reranking, not a claim of semantic model training.
        weights = {}
        for rating, features in rows:
            for name, value in json.loads(features).items():
                weights[name] = weights.get(name, 0) + rating * (value - .5)
        return {name: max(-.15, min(.15, value / max(5, len(rows)))) for name, value in weights.items()}
