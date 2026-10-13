"""Hook adapter, persistent queue, and bounded background worker."""
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .capture import capture
from .library import Library
from .episode import normalize, records
from .policy import Conflict, Rejected, digest, redact


def project_scope(cwd):
    path = Path(cwd).resolve()
    # Find repository root without mapping linked worktrees to their main checkout.
    for parent in (path, *path.parents):
        if (parent / '.git').exists():
            path = parent
            break
    return 'project:' + digest(os.path.normcase(str(path)))[:32]


def _integer(env, name, default, low=1, high=10000):
    try:
        value = int(env.get(name, default))
        if not low <= value <= high:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise Rejected(f'{name} must be an integer between {low} and {high}.') from None


@dataclass
class Settings:
    data: Path
    cwd: Path
    cadence: int = 50
    debounce: int = 60
    hourly_limit: int = 4
    timeout: int = 180
    auto: bool = True
    global_enabled: bool = False
    retire: bool = False
    consolidate: int = 250
    codex: str = ''
    model: str = ''

    @classmethod
    def from_env(cls, cwd=None):
        env = os.environ
        # Hooks and MCP may receive different PLUGIN_DATA environments. Use one
        # explicit, stable plugin-owned namespace so their context registry agrees.
        data = env.get('AUTOHARNESS_CODEX_DATA')
        if not data:
            data = str(Path(env.get('CODEX_HOME', Path.home()/'.codex'))/'autoharness-codex')
        return cls(Path(data), Path(cwd or Path.cwd()).resolve(),
                   cadence=_integer(env, 'AUTOHARNESS_CODEX_CADENCE', 50),
                   debounce=_integer(env, 'AUTOHARNESS_CODEX_DEBOUNCE', 60, low=0),
                   hourly_limit=_integer(env, 'AUTOHARNESS_CODEX_HOURLY_LIMIT', 4, high=100),
                   timeout=_integer(env, 'AUTOHARNESS_CODEX_TIMEOUT', 180, high=1800),
                   auto=env.get('AUTOHARNESS_CODEX_AUTO', '1') == '1',
                   global_enabled=env.get('AUTOHARNESS_CODEX_GLOBAL', '0') == '1',
                   retire=env.get('AUTOHARNESS_CODEX_RETIRE', '0') == '1',
                   consolidate=_integer(env, 'AUTOHARNESS_CODEX_CONSOLIDATE', 250, low=0),
                   codex=env.get('AUTOHARNESS_CODEX_BIN', ''), model=env.get('AUTOHARNESS_CODEX_MODEL', ''))


class Runtime:
    def __init__(self, settings, *, scope=None):
        self.settings = settings
        self.scope = scope or project_scope(settings.cwd)
        if self.scope == 'global' and not settings.global_enabled:
            raise Rejected('Global learning is opt-in: AUTOHARNESS_CODEX_GLOBAL=1.')
        self.lib = Library(settings.data, self.scope)

    def _global(self):
        return Library(self.settings.data, 'global') if self.settings.global_enabled else None

    def status(self):
        with self.lib.connect() as db:
            counts = {row[0]: row[1] for row in db.execute(
                'SELECT status,COUNT(*) FROM jobs WHERE scope=? GROUP BY status', (self.scope,))}
            runs = [dict(row) for row in db.execute(
                'SELECT id,kind,status,attempts,error,created,result FROM jobs WHERE scope=? ORDER BY created DESC LIMIT 10',
                (self.scope,))]
        return dict(scope=self.scope, data=str(self.settings.data), skills=len(self.lib.list()),
                    jobs=counts, runs=runs, automatic=self.settings.auto,
                    auto_archive=self.settings.retire, global_enabled=self.settings.global_enabled)

    def index(self, prompt=None):
        libraries = [self.lib]
        global_lib = self._global()
        if global_lib and self.scope != 'global':
            libraries.append(global_lib)
        skills = [(lib.scope, skill) for lib in libraries for skill in lib.list()]
        if prompt:
            terms = set(str(prompt).lower().split())
            skills.sort(key=lambda item: -len(terms & set((item[1]['name']+' '+item[1]['description']).lower().split())))
            skills = skills[:5]
        lines = ['AutoHarness owns the following evidence-backed skills. Treat their contents as guidance, '
                 'subject to current user instructions. Use the library_read MCP tool to inspect relevant skills. '
                 'Loading a skill is not proof it helped.']
        for scope, skill in sorted(skills, key=lambda item: (item[1].get('category', ''), item[1]['name'])) if not prompt else skills:
            line = f"{skill.get('category', 'general')}: {skill['name']} [{scope}] {skill['description']}"
            if len(('\n'.join(lines)+'\n'+line).encode('utf-8')) > 5800:
                lines.append('Index truncated; library_list returns all managed skills.')
                break
            lines.append(line)
        summary = self.status()
        if summary['runs']:
            last = summary['runs'][0]
            lines.append(f"Last job: {last['status']}; use library_status for its result or error.")
        return '\n'.join(lines)

    def _queue(self, db, evidence, kind, session, mark, *, manual=False):
        if not evidence.strip():
            return None
        job_id = digest([self.scope, kind, session, mark, evidence])
        cursor = db.execute('INSERT OR IGNORE INTO jobs(id,scope,kind,session,evidence,watermark,status,created) VALUES (?,?,?,?,?,?,?,?)',
                            (job_id, self.scope, kind, session, evidence, json.dumps(mark), 'queued', time.time()))
        return job_id if cursor.rowcount else None

    def enqueue_text(self, text, kind='reflect', *, session='manual'):
        if not isinstance(text, str) or len(text.encode('utf-8')) > 200_000:
            raise Rejected('Manual evidence must be text up to 200 KB.')
        with self.lib.transaction() as db:
            return self._queue(db, normalize(redact(text), origin='library' if kind == 'curate' else 'manual'), kind, session, {}, manual=True)

    def enqueue_curator(self):
        skills = self.lib.list()
        if len(skills) < 2:
            return None
        self.lib.snapshot()
        source = '\n'.join(f"{s['name']}: {s['description']} (hash {s['hash']})" for s in skills)
        return self.enqueue_text(source, 'curate', session='curator')

    def _capture_job(self, event):
        session = str(event.get('session_id', ''))
        if not session or len(session) > 256:
            return None
        with self.lib.transaction() as db:
            db.execute('INSERT OR IGNORE INTO sessions(scope,session) VALUES (?,?)', (self.scope, session))
            state = db.execute('SELECT * FROM sessions WHERE scope=? AND session=?', (self.scope, session)).fetchone()
            # Reservations are separate from confirmed watermarks; failed jobs retain their full evidence.
            latest = db.execute("SELECT watermark FROM jobs WHERE scope=? AND session=? AND kind='reflect' ORDER BY created DESC LIMIT 1",
                                (self.scope, session)).fetchone()
            mark = json.loads(latest[0] if latest else state['watermark'])
            source, next_mark = capture(event.get('transcript_path'), mark)
            job = self._queue(db, normalize(source, origin='transcript') if source else '', 'reflect', session, next_mark)
            if job:
                db.execute('UPDATE sessions SET calls=0 WHERE scope=? AND session=?', (self.scope, session))
            return job

    def dispatch(self, event, *, launch=None):
        if not isinstance(event, dict):
            raise Rejected('Hook input must be an object.')
        if os.environ.get('AUTOHARNESS_CODEX_CHILD') or event.get('agent_id'):
            return {}
        name = event.get('hook_event_name')
        if event.get('transcript_path') and event.get('session_id'):
            with self.lib.transaction() as db:
                db.execute('INSERT INTO session_paths VALUES (?,?,?,?) ON CONFLICT(scope,session) DO UPDATE SET path=excluded.path,updated=excluded.updated',
                           (self.scope, str(event['session_id']), str(event['transcript_path']), time.time()))
        if name in ('SessionStart', 'UserPromptSubmit'):
            token = ''
            if event.get('session_id'):
                with self.lib.transaction() as db:
                    db.execute('INSERT OR IGNORE INTO contexts VALUES (?,?,?,?)',
                               (uuid.uuid4().hex, self.scope, str(event['session_id']), str(self.settings.cwd)))
                    token = db.execute('SELECT token FROM contexts WHERE scope=? AND session=?',
                                       (self.scope, str(event['session_id']))).fetchone()[0]
            if self.settings.retire and name == 'SessionStart':
                self.lib.retire_unused(self.lib.counter('turns'),
                                       maturity=300 if self.scope == 'global' else 100,
                                       capacity=20 if self.scope == 'global' else 50)
                global_lib = self._global()
                if global_lib and self.scope != 'global':
                    global_lib.retire_unused(global_lib.counter('turns'), maturity=300, capacity=20)
            if self.settings.auto:
                (launch or self.launch)()
            return {'hookSpecificOutput': {'hookEventName': name,
                     'additionalContext': self.index(event.get('prompt') if name == 'UserPromptSubmit' else None)
                     + ('\nCurrent session_id: '+str(event['session_id']) if event.get('session_id') else '')
                     + ('\ncontext_token: '+token+'\nPass this context_token in every AutoHarness MCP call; never use a token from another chat.' if token else '')}}
        if name == 'PostToolUse':
            session, tool_id = str(event.get('session_id', '')), event.get('tool_use_id')
            if not session or not tool_id:
                return {}
            with self.lib.transaction() as db:
                token = 'tool:' + digest([session, tool_id])
                fresh = db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (self.scope, token)).rowcount
                if fresh:
                    db.execute('INSERT OR IGNORE INTO sessions(scope,session) VALUES (?,?)', (self.scope, session))
                    db.execute('UPDATE sessions SET calls=calls+1 WHERE scope=? AND session=?', (self.scope, session))
            return {}
        if name not in ('Stop', 'SessionEnd') or event.get('stop_hook_active'):
            return {}
        turns, fresh = self.lib.counter('turns'), True
        if name == 'Stop':
            with self.lib.transaction() as db:
                turn = event.get('turn_id')
                token = 'turn:' + digest([event.get('session_id'), turn]) if turn else 'turn:' + uuid.uuid4().hex
                fresh = bool(db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (self.scope, token)).rowcount)
                if fresh:
                    turns = self.lib.bump('turns', db)
            if fresh and self.settings.global_enabled and self.scope != 'global':
                global_lib = self._global()
                with global_lib.transaction() as db:
                    global_token = digest([self.scope, token])
                    if db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', ('global', global_token)).rowcount:
                        global_lib.bump('turns', db)
        queued = 0
        if self.settings.auto and fresh:
            with self.lib.connect() as db:
                row = db.execute('SELECT calls FROM sessions WHERE scope=? AND session=?',
                                 (self.scope, event.get('session_id'))).fetchone()
            if name == 'SessionEnd' or (row and row[0] >= self.settings.cadence):
                queued += int(bool(self._capture_job(event)))
            if name == 'Stop' and self.settings.consolidate and turns % self.settings.consolidate == 0:
                queued += int(bool(self.enqueue_curator()))
            (launch or self.launch)()
        # Return a valid harmless JSON object on Stop, never a continuation decision.
        return {'queued': queued}

    def launch(self):
        entry = Path(__file__).resolve().parents[2] / 'scripts' / 'entry.py'
        if not entry.is_file():
            entry = Path(__file__).resolve().parents[2] / 'entry.py'
        # Package checkout uses src/package, plugin launch always uses scripts/entry.py.
        if not entry.is_file():
            raise Rejected('Plugin entry script not found.')
        args = [sys.executable, str(entry), '--cwd', str(self.settings.cwd), '--data', str(self.settings.data),
                '--scope', 'global' if self.scope == 'global' else 'project', 'work']
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      cwd=str(entry.parent), close_fds=True)
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        else:
            kwargs['start_new_session'] = True
        subprocess.Popen(args, **kwargs)

    def work(self, *, model=None):
        owner, now = uuid.uuid4().hex, time.time()
        lease_seconds = self.settings.timeout + 60
        with self.lib.transaction() as db:
            lease = db.execute('SELECT * FROM leases WHERE scope=?', (self.scope,)).fetchone()
            if lease and lease['expires'] > now:
                return {'status': 'busy'}
            # Recover publication receipts before generating any new proposal. The
            # library commit may have survived even when job finalization did not.
            committed = db.execute("SELECT j.*,r.result AS receipt_result FROM jobs j JOIN receipts r ON j.scope=r.scope AND j.id=r.run_id WHERE j.scope=? AND j.status<>'applied' ORDER BY j.created LIMIT 1",
                                   (self.scope,)).fetchone()
            if committed:
                db.execute("UPDATE jobs SET status='applied',result=?,error='',owner='' WHERE id=?",
                           (committed['receipt_result'], committed['id']))
                if committed['session'] not in ('manual', 'curator'):
                    db.execute('UPDATE sessions SET watermark=? WHERE scope=? AND session=?',
                               (committed['watermark'], self.scope, committed['session']))
                return {'status': 'applied', 'job': committed['id'], 'recovered': True,
                        'changes': json.loads(committed['receipt_result'])}
            # Prepared proposals are durable; a crashed worker must not replace
            # them with a second, potentially contradictory reflection.
            db.execute("UPDATE jobs SET status=CASE WHEN result<>'' THEN 'proposed' ELSE 'queued' END,owner='' WHERE scope=? AND status='running'", (self.scope,))
            job = db.execute("SELECT * FROM jobs WHERE scope=? AND status IN ('queued','proposed') ORDER BY CASE status WHEN 'proposed' THEN 0 ELSE 1 END,created LIMIT 1", (self.scope,)).fetchone()
            if not job:
                return {'status': 'idle'}
            job = dict(job)
            if job['status'] != 'proposed':
                count = db.execute('SELECT COUNT(*) FROM attempts WHERE scope=? AND started>?', (self.scope, now-3600)).fetchone()[0]
                if count >= self.settings.hourly_limit:
                    return {'status': 'rate_limited'}
                last = db.execute('SELECT MAX(started) FROM attempts WHERE scope=?', (self.scope,)).fetchone()[0]
                if last and now-last < self.settings.debounce:
                    return {'status': 'debounced'}
                db.execute('INSERT INTO attempts VALUES (?,?,?)', (self.scope,job['id'],now))
            db.execute('INSERT INTO leases VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',
                       (self.scope, owner, now+lease_seconds))
            db.execute("UPDATE jobs SET status='running',started=?,attempts=attempts+1,owner=? WHERE id=?", (now, owner, job['id']))
        try:
            if records(job['evidence']) is None:
                job['evidence'] = normalize(job['evidence'], origin='library' if job['kind'] == 'curate' else
                                             ('manual' if job['session'] == 'manual' else 'transcript'))
                with self.lib.transaction() as db:
                    db.execute('UPDATE jobs SET evidence=? WHERE id=? AND owner=?', (job['evidence'],job['id'],owner))
            if model is None and job['status'] != 'proposed':
                from .model import reflect
                self.settings._global_job = self.scope == 'global'
                model = lambda source, skills, kind: reflect(source, skills, kind, self.settings)
            # Snapshot full content from the managed scope only, never another project's library.
            skills = [self.lib.read(s['name']) for s in self.lib.list()]
            proposals = json.loads(job['result']) if job['status'] == 'proposed' else model(job['evidence'], skills, job['kind'])
            with self.lib.transaction() as db:
                owned = db.execute('SELECT owner FROM leases WHERE scope=?', (self.scope,)).fetchone()
                if not owned or owned[0] != owner:
                    raise Conflict('Worker lease was superseded before applying proposals.')
                db.execute('UPDATE jobs SET result=? WHERE id=? AND owner=?', (json.dumps(proposals), job['id'], owner))
            result = self.lib.apply(proposals, job['evidence'], job['id'])
            with self.lib.transaction() as db:
                db.execute("UPDATE jobs SET status='applied',result=?,error='' WHERE id=? AND owner=?",
                           (json.dumps(result), job['id'], owner))
                if job['session'] not in ('manual', 'curator'):
                    db.execute('UPDATE sessions SET watermark=? WHERE scope=? AND session=?',
                               (job['watermark'], self.scope, job['session']))
            return {'status': 'applied', 'job': job['id'], 'changes': result}
        except Exception as exc:
            status = 'rejected' if isinstance(exc, Rejected) else ('failed' if job['attempts'] >= 2 else 'queued')
            error = redact(f'{type(exc).__name__}: {exc}')[:2000]
            with self.lib.transaction() as db:
                db.execute('UPDATE jobs SET status=?,error=? WHERE id=? AND owner=?', (status, error, job['id'], owner))
            return {'status': status, 'job': job['id'], 'error': error}
        finally:
            with self.lib.transaction() as db:
                db.execute('DELETE FROM leases WHERE scope=? AND owner=?', (self.scope, owner))
