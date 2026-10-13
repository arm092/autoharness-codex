"""User commands and fail-open hook entry."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from .model import doctor
from .policy import Rejected, redact
from .runtime import Runtime, Settings


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_file(path, cap):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > cap:
        raise Rejected('Input file is missing or exceeds its byte limit.')
    return path.read_text(encoding='utf-8-sig')


def main(argv=None):
    parser = argparse.ArgumentParser(description='AutoHarness for Codex')
    parser.add_argument('--cwd')
    parser.add_argument('--data')
    parser.add_argument('--scope', choices=['project', 'global'], default='project')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('hook', 'doctor', 'status', 'list', 'curate', 'work'):
        commands.add_parser(command)
    commands.add_parser('mcp').add_argument('--require-context', action='store_true')
    learn = commands.add_parser('learn')
    learn.add_argument('--episode-file', required=True)
    learn.add_argument('--wait', action='store_true')
    for command in ('read', 'history'):
        commands.add_parser(command).add_argument('name')
    search = commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--limit',type=int,default=5)
    restore = commands.add_parser('restore')
    restore.add_argument('name')
    restore.add_argument('--version', type=int, required=True)
    restore.add_argument('--expected-hash', required=True)
    pin = commands.add_parser('pin')
    pin.add_argument('name')
    pin.add_argument('--off', action='store_true')
    feedback = commands.add_parser('feedback')
    feedback.add_argument('name')
    feedback.add_argument('kind', choices=['uses', 'views', 'helpful'])
    commands.add_parser('retry').add_argument('job_id')
    for command in ('preview', 'apply'):
        sub = commands.add_parser(command)
        sub.add_argument('--job-id', required=True)
        sub.add_argument('--proposal-file', required=True)
        if command == 'apply':
            sub.add_argument('--allow-scripts', action='store_true')
    args = parser.parse_args(argv)
    try:
        event = None
        if args.command == 'hook':
            raw = sys.stdin.read(512_001)
            if len(raw) > 512_000:
                raise Rejected('Oversized hook event.')
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise Rejected('Hook input must be an object.')
        settings = Settings.from_env(event.get('cwd') if event else args.cwd)
        if args.data:
            settings.data = Path(args.data).resolve()
        if args.command == 'doctor':
            result = doctor(settings)
            emit(result)
            return 0 if result['ok'] else 1
        rt = Runtime(settings, scope='global' if args.scope == 'global' else None)
        if args.command == 'hook':
            print(json.dumps(rt.dispatch(event), ensure_ascii=False))
        elif args.command == 'mcp':
            from .mcp import Server, serve
            serve(Server(rt, require_context=args.require_context))
        elif args.command == 'status':
            emit(rt.status())
        elif args.command == 'list':
            emit(rt.lib.list(include_archived=True))
        elif args.command == 'read':
            emit(rt.lib.read(args.name, include_archived=True, count_view=True))
        elif args.command == 'history':
            emit(rt.lib.history(args.name))
        elif args.command == 'search':
            emit(rt.search(args.query,args.limit))
        elif args.command == 'restore':
            emit(rt.lib.restore(args.name, args.version, args.expected_hash))
        elif args.command == 'pin':
            rt.lib.pin(args.name, not args.off)
            emit({'pinned': not args.off})
        elif args.command == 'feedback':
            rt.lib.feedback(args.name, args.kind)
            emit({'recorded': args.kind})
        elif args.command == 'learn':
            job = rt.enqueue_text(read_file(args.episode_file, 200_000))
            if args.wait:
                result = rt.work()
                emit(result)
                return 0 if result['status'] == 'applied' else 1
            if job:
                rt.launch()
            emit({'status': 'queued' if job else 'already_queued', 'job_id': job})
        elif args.command == 'curate':
            job = rt.enqueue_curator()
            if job:
                rt.launch()
            emit({'queued': bool(job), 'job_id': job})
        elif args.command == 'work':
            results = []
            for _ in range(16):
                result = rt.work()
                results.append(result)
                if result['status'] != 'applied':
                    break
            emit(results)
            return int(any(r['status'] in ('failed', 'rejected') for r in results))
        elif args.command == 'retry':
            with rt.lib.transaction() as db:
                changed = db.execute("UPDATE jobs SET status='queued',attempts=0,error='' WHERE scope=? AND id=? AND status IN ('failed','rejected')",
                                     (rt.scope, args.job_id)).rowcount
            if not changed:
                raise Rejected('Only failed/rejected jobs in this scope can be retried.')
            rt.launch()
            emit({'status': 'queued'})
        elif args.command in ('preview', 'apply'):
            proposals = json.loads(read_file(args.proposal_file, 512_000))
            if isinstance(proposals, dict):
                proposals = proposals['proposals']
            with rt.lib.connect() as db:
                job = db.execute('SELECT * FROM jobs WHERE scope=? AND id=?', (rt.scope, args.job_id)).fetchone()
            if not job or job['status'] not in ('queued', 'proposed', 'rejected', 'failed'):
                raise Rejected('Job not available for review.')
            if args.command == 'preview':
                emit(rt.lib.preview(proposals, job['evidence']))
            else:
                # Reviewed scripts are admitted synchronously, never executed by this process.
                owner = uuid.uuid4().hex
                with rt.lib.transaction() as db:
                    lease = db.execute('SELECT expires FROM leases WHERE scope=?', (rt.scope,)).fetchone()
                    if lease and lease[0] > time.time():
                        raise Rejected('A worker currently owns this library; retry admission after it completes.')
                    claimed = db.execute("UPDATE jobs SET status='running',owner=? WHERE id=? AND status IN ('queued','proposed','rejected','failed')",
                                         (owner, job['id'])).rowcount
                    if not claimed:
                        raise Rejected('Job changed during admission.')
                    db.execute('INSERT INTO leases VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',
                               (rt.scope, owner, time.time()+60))
                try:
                    result = rt.lib.apply(proposals, job['evidence'], job['id'], allow_scripts=args.allow_scripts)
                    with rt.lib.transaction() as db:
                        db.execute("UPDATE jobs SET status='applied',result=?,error='' WHERE id=?", (json.dumps(result), job['id']))
                    emit(result)
                except Exception:
                    with rt.lib.transaction() as db:
                        db.execute("UPDATE jobs SET status='rejected' WHERE id=? AND owner=?", (job['id'], owner))
                    raise
                finally:
                    with rt.lib.transaction() as db:
                        db.execute('DELETE FROM leases WHERE scope=? AND owner=?', (rt.scope, owner))
        return 0
    except Exception as exc:
        error = redact(f'{type(exc).__name__}: {exc}')[:2000]
        if args.command == 'hook':
            print('{}')
            print('autoharness-codex hook: '+error, file=sys.stderr)
            return 0
        emit({'error': error})
        return 1
