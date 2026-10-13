"""Immutable skill versions, with a single SQLite commit publishing each change group.

Preparing a revision never changes a live skill. Crashes before commit leave an
unreferenced directory; crashes after commit leave complete referenced versions.
The active library is read from SQLite, so no recovery can clobber newer edits.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .policy import (Conflict, Rejected, digest, frontmatter, redact, safe_directory,
                     safe_name, validate_content)


SCHEMA = '''
CREATE TABLE IF NOT EXISTS skills (
 scope TEXT, name TEXT, hash TEXT, status TEXT, pinned INTEGER DEFAULT 0,
 uses INTEGER DEFAULT 0, views INTEGER DEFAULT 0, helpful INTEGER DEFAULT 0,
 anchor INTEGER DEFAULT 0, PRIMARY KEY(scope,name));
CREATE TABLE IF NOT EXISTS versions (
 scope TEXT, name TEXT, version INTEGER, hash TEXT, body TEXT, files TEXT,
 status TEXT, reason TEXT, evidence TEXT, created REAL, PRIMARY KEY(scope,name,version));
CREATE TABLE IF NOT EXISTS receipts (scope TEXT, run_id TEXT, input_hash TEXT, result TEXT,
 PRIMARY KEY(scope,run_id));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, scope TEXT, kind TEXT, session TEXT, evidence TEXT, watermark TEXT,
 status TEXT, created REAL, started REAL, attempts INTEGER DEFAULT 0,
 result TEXT DEFAULT '', error TEXT DEFAULT '', owner TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS sessions (
 scope TEXT, session TEXT, watermark TEXT DEFAULT '{}', calls INTEGER DEFAULT 0,
 PRIMARY KEY(scope,session));
CREATE TABLE IF NOT EXISTS events (scope TEXT, id TEXT, PRIMARY KEY(scope,id));
CREATE TABLE IF NOT EXISTS counters (scope TEXT, key TEXT, value INTEGER DEFAULT 0,
 PRIMARY KEY(scope,key));
CREATE TABLE IF NOT EXISTS leases (scope TEXT PRIMARY KEY, owner TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS session_paths (scope TEXT,session TEXT,path TEXT,updated REAL,PRIMARY KEY(scope,session));
CREATE TABLE IF NOT EXISTS attempts (scope TEXT,job TEXT,started REAL);
'''


class Library:
    def __init__(self, root, scope):
        if not isinstance(scope, str) or (scope != 'global' and not scope.startswith('project:')):
            raise Rejected('Unknown library scope.')
        self.root, self.scope = safe_directory(root), scope
        self.root.mkdir(parents=True, exist_ok=True)
        db_path = self.root / 'library.sqlite3'
        if db_path.is_symlink():
            raise Rejected('Database path cannot be a symlink.')
        with self.connect() as db:
            db.executescript(SCHEMA)

    def _connection(self):
        safe_directory(self.root)
        if (self.root / 'library.sqlite3').is_symlink():
            raise Rejected('Database path cannot be a symlink.')
        db = sqlite3.connect(self.root / 'library.sqlite3', timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=20000')
        return db

    @contextmanager
    def connect(self):
        db = self._connection()
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        db = self._connection()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _skill(self, db, name):
        return db.execute('SELECT * FROM skills WHERE scope=? AND name=?', (self.scope, name)).fetchone()

    def _version(self, db, name, hash_value):
        return db.execute('SELECT * FROM versions WHERE scope=? AND name=? AND hash=? ORDER BY version DESC LIMIT 1',
                          (self.scope, name, hash_value)).fetchone()

    def revision_path(self, name, hash_value):
        safe_name(name)
        if len(hash_value) != 64 or any(c not in '0123456789abcdef' for c in hash_value):
            raise Rejected('Invalid revision hash.')
        return safe_directory(self.root / 'revisions' / digest(self.scope)[:24] / name / hash_value)

    def _persist_revision(self, name, hash_value, body, files, evidence):
        final = self.revision_path(name, hash_value)
        if final.exists():
            # Immutable existing content must match, including support files.
            expected = {'SKILL.md': body, **files,
                        'references/evidence-' + digest(evidence)[:16] + '.md': evidence}
            for rel, content in expected.items():
                path = final / rel
                safe_directory(path)
                if not path.is_file() or path.read_text(encoding='utf-8') != content:
                    raise Conflict('An immutable revision was changed on disk.')
            return
        final.parent.mkdir(parents=True, exist_ok=True)
        temp = safe_directory(final.parent / ('.prepare-' + uuid.uuid4().hex))
        temp.mkdir()
        for rel, content in {'SKILL.md': body, **files,
                             'references/evidence-' + digest(evidence)[:16] + '.md': evidence}.items():
            target = temp / rel
            safe_directory(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temp, final)

    def apply(self, proposals, source, run_id, *, allow_scripts=False, validate_only=False):
        if not isinstance(proposals, list) or len(proposals) > 16 or not isinstance(source, str):
            raise Rejected('Expected at most 16 proposals and episode evidence.')
        if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
            raise Rejected('Invalid run id.')
        input_hash = digest([proposals, source, allow_scripts])
        source = redact(source)
        results = []
        with self.transaction() as db:
            receipt = db.execute('SELECT * FROM receipts WHERE scope=? AND run_id=?', (self.scope, run_id)).fetchone()
            if receipt:
                if receipt['input_hash'] != input_hash:
                    raise Conflict('Run id was reused for different proposals.')
                return json.loads(receipt['result'])
            seen = set()
            for proposal in proposals:
                if not isinstance(proposal, dict):
                    raise Rejected('Each proposal must be an object.')
                name = safe_name(proposal.get('name'))
                if name in seen:
                    raise Rejected('Use one complete proposal per skill in a batch.')
                seen.add(name)
                quote = proposal.get('evidence', '')
                reason = proposal.get('reason', '')
                if not isinstance(quote, str) or len(quote.strip()) < 8 or len(quote) > 8000 \
                        or quote not in source or not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
                    raise Rejected('Evidence must quote the supplied episode; reason is required.')
                action = proposal.get('action')
                if action == 'delete':
                    action = 'archive'
                current = self._skill(db, name)
                if action == 'create':
                    if current:
                        raise Conflict('Skill name already belongs to this library, including its archive.')
                    body, files, status = proposal.get('body'), proposal.get('files', {}), 'active'
                else:
                    if not current or current['status'] != 'active':
                        raise Conflict('Target is not a live plugin-owned skill.')
                    if proposal.get('expected_hash') != current['hash']:
                        raise Conflict('Skill changed since this proposal was produced.')
                    previous = self._version(db, name, current['hash'])
                    body, files, status = previous['body'], json.loads(previous['files']), 'active'
                    if action == 'update':
                        body, files = proposal.get('body'), proposal.get('files', files)
                    elif action == 'patch':
                        old, new = proposal.get('old_string'), proposal.get('new_string')
                        if not isinstance(old, str) or not old or body.count(old) != 1 or not isinstance(new, str):
                            raise Rejected('Patch must match one unique nonempty string.')
                        body = body.replace(old, new, 1)
                    elif action == 'remove_file':
                        rel = proposal.get('path')
                        from .policy import safe_relative
                        safe_relative(rel)
                        files.pop(rel, None)
                    elif action == 'archive':
                        if current['pinned']:
                            raise Rejected('Unpin a skill explicitly before archiving or merging it.')
                        status = 'archived'
                        target_name = proposal.get('absorbed_into')
                        if target_name:
                            target = self._skill(db, safe_name(target_name))
                            if not target or target['status'] != 'active' or target_name == name:
                                raise Rejected('Merge requires a live surviving skill.')
                            if target_name not in seen:
                                raise Rejected('Merge must include its surviving skill before archiving the source.')
                            target_version = self._version(db, target_name, target['hash'])
                            target_files = json.loads(target_version['files'])
                            for rel, content in files.items():
                                if content not in target_files.values():
                                    raise Rejected('Merge must preserve every support file before archiving.')
                    else:
                        raise Rejected('Unknown proposal action.')
                # Existing approved scripts may remain; adding or changing them requires manual admission.
                previous_files = json.loads(self._version(db, name, current['hash'])['files']) if current else {}
                has_new_scripts = any(rel.startswith('scripts/') and content != previous_files.get(rel)
                                      for rel, content in files.items()) if isinstance(files, dict) else False
                validate_content(name, body, files, scope=self.scope,
                                 allow_scripts=allow_scripts or not has_new_scripts)
                # Include provenance and status: every accepted change gets a distinct stable version.
                hash_value = digest([body, files, quote, reason, status])
                if not validate_only:
                    self._persist_revision(name, hash_value, body, files, quote)
                version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM versions WHERE scope=? AND name=?',
                                     (self.scope, name)).fetchone()[0]
                db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (self.scope, name, version, hash_value, body, json.dumps(files, ensure_ascii=False),
                            status, redact(reason), quote, time.time()))
                if current:
                    db.execute('UPDATE skills SET hash=?,status=? WHERE scope=? AND name=?',
                               (hash_value, status, self.scope, name))
                else:
                    db.execute('INSERT INTO skills(scope,name,hash,status,anchor) VALUES (?,?,?,?,?)',
                               (self.scope, name, hash_value, status, self.counter('turns', db)))
                results.append(dict(name=name, action=action, hash=hash_value, version=version, status=status))
            if validate_only:
                db.rollback()
            else:
                db.execute('INSERT INTO receipts VALUES (?,?,?,?)',
                           (self.scope, run_id, input_hash, json.dumps(results)))
        return results

    def preview(self, proposals, source):
        return self.apply(proposals, source, 'preview-' + uuid.uuid4().hex, validate_only=True)

    def read(self, name, *, include_archived=False, count_view=False):
        safe_name(name)
        with self.connect() as db:
            skill = self._skill(db, name)
            if not skill or (skill['status'] != 'active' and not include_archived):
                raise Conflict('Skill not found in this scope.')
            version = self._version(db, name, skill['hash'])
            result = dict(skill) | dict(version)
            result['files'] = json.loads(result['files'])
            result['path'] = str(self.revision_path(name, skill['hash']) / 'SKILL.md')
            if count_view:
                db.execute('UPDATE skills SET views=views+1 WHERE scope=? AND name=?', (self.scope, name))
            return result

    def list(self, *, include_archived=False):
        with self.connect() as db:
            names = db.execute('SELECT name FROM skills WHERE scope=? ORDER BY name', (self.scope,)).fetchall()
        results = []
        for row in names:
            try:
                skill = self.read(row['name'], include_archived=include_archived)
            except Conflict:
                continue
            fields, _ = frontmatter(skill['body'])
            results.append({key: skill[key] for key in ('name', 'hash', 'status', 'pinned', 'uses', 'views', 'helpful', 'path')}
                           | fields)
        return results

    def history(self, name):
        safe_name(name)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT version,hash,status,reason,evidence,created FROM versions WHERE scope=? AND name=? ORDER BY version',
                (self.scope, name))]

    def restore(self, name, version, expected_hash):
        safe_name(name)
        with self.transaction() as db:
            current = self._skill(db, name)
            old = db.execute('SELECT * FROM versions WHERE scope=? AND name=? AND version=?',
                             (self.scope, name, version)).fetchone()
            if not current or not old or current['hash'] != expected_hash:
                raise Conflict('Restore target is missing or changed.')
            self._persist_revision(name, old['hash'], old['body'], json.loads(old['files']), old['evidence'])
            next_version = db.execute('SELECT MAX(version)+1 FROM versions WHERE scope=? AND name=?',
                                      (self.scope, name)).fetchone()[0]
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (self.scope, name, next_version, old['hash'], old['body'], old['files'], 'active',
                        f'Restored version {version}.', old['evidence'], time.time()))
            db.execute('UPDATE skills SET hash=?,status=? WHERE scope=? AND name=?',
                       (old['hash'], 'active', self.scope, name))
        return self.read(name)

    def pin(self, name, enabled):
        with self.transaction() as db:
            if not self._skill(db, safe_name(name)):
                raise Conflict('Skill not found.')
            db.execute('UPDATE skills SET pinned=? WHERE scope=? AND name=?', (int(bool(enabled)), self.scope, name))

    def feedback(self, name, kind):
        if kind not in ('uses', 'views', 'helpful'):
            raise Rejected('Feedback must be uses, views, or helpful.')
        with self.transaction() as db:
            if not self._skill(db, safe_name(name)):
                raise Conflict('Skill not found.')
            db.execute(f'UPDATE skills SET {kind}={kind}+1 WHERE scope=? AND name=?', (self.scope, name))

    def snapshot(self, keep=5):
        """Scope-only recovery snapshot; immutable revision files remain in place."""
        directory = safe_directory(self.root / 'snapshots')
        directory.mkdir(exist_ok=True)
        prefix = digest(self.scope)[:24] + '-'
        name = prefix + str(time.time_ns()) + '-' + uuid.uuid4().hex + '.json'
        target = safe_directory(directory / name)
        with self.connect() as db:
            db.execute('BEGIN')
            skills = [dict(r) for r in db.execute('SELECT * FROM skills WHERE scope=?', (self.scope,))]
            versions = [dict(r) for r in db.execute('SELECT * FROM versions WHERE scope=? ORDER BY name,version', (self.scope,))]
        with target.open('x', encoding='utf-8') as handle:
            json.dump(dict(scope=self.scope, skills=skills, versions=versions), handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for old in sorted(directory.glob(prefix+'*.json'))[:-max(1, keep)]:
            safe_directory(old)
            old.unlink()
        return str(target)

    def counter(self, key, db=None):
        if db is None:
            with self.connect() as handle:
                return self.counter(key, handle)
        row = db.execute('SELECT value FROM counters WHERE scope=? AND key=?', (self.scope, key)).fetchone()
        return row[0] if row else 0

    def bump(self, key, db):
        db.execute('INSERT INTO counters VALUES (?,?,1) ON CONFLICT(scope,key) DO UPDATE SET value=value+1',
                   (self.scope, key))
        return self.counter(key, db)

    def retire_unused(self, request_count, *, maturity=100, capacity=50):
        """Explicit opt-in compatibility policy; pin/helpfulness always protect knowledge."""
        with self.connect() as db:
            skills = [dict(row) for row in db.execute('SELECT * FROM skills WHERE scope=? AND status=?',
                                                     (self.scope, 'active'))]
        mature = [s for s in skills if request_count - s['anchor'] >= maturity and not s['pinned'] and not s['helpful']]
        names = [s['name'] for s in mature if not s['uses'] and not s['views']]
        pool = sorted((s for s in mature if s['uses']), key=lambda s: (s['uses'] / max(1, request_count-s['anchor']), s['name']))
        names += [s['name'] for s in pool[:max(0, len(pool)-capacity)]]
        for name in names:
            skill = self.read(name)
            source = 'Compatibility lifecycle policy selected an unused or low-rate skill.'
            self.apply([dict(action='archive', name=name, expected_hash=skill['hash'], reason=source, evidence=source)],
                       source, 'lifecycle-' + uuid.uuid4().hex)
        return names
