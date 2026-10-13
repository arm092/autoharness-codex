"""MCP stdio transport with project-bound tools and durable proposal staging."""
import difflib
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .policy import Rejected, redact
from .runtime import Runtime


def tool(name, description, properties=None, required=None, *, read_only=True):
    return dict(name=name, description=description,
                inputSchema=dict(type='object', properties=properties or {},
                                 required=required or [], additionalProperties=False),
                annotations=dict(readOnlyHint=read_only, destructiveHint=False, openWorldHint=False))


TEXT = {'type': 'string'}
SCOPE = {'type': 'string', 'enum': ['project', 'global']}
NAME = {'name': TEXT, 'scope': SCOPE}
PROPOSALS = {'job_id': TEXT, 'proposals': {'type': 'array', 'items': {'type': 'object'}}}
TOOLS = [
    tool('library_search', 'Find relevant managed skills for EN/RU/HY/FR/ES technical queries; returns no unrelated recommendations.',
         {'query':TEXT,'limit':{'type':'integer','minimum':1},'scope':SCOPE}, ['query']),
    tool('library_list', 'List plugin-owned skills in the current project or opt-in global library.', {'scope': SCOPE, 'include_archived': {'type': 'boolean'}}),
    tool('library_read', 'Read a managed skill and its support files; increments views, not successful uses.', NAME, ['name'], read_only=False),
    tool('library_history', 'Inspect immutable versions and provenance before choosing a restore.', NAME, ['name']),
    tool('library_status', 'Inspect queued, proposed, applied, rejected and failed jobs. Staging is not success.', {'scope': SCOPE}),
    tool('learn_episode', 'Queue this session’s registered transcript for reflection. Hooks must have registered it first.', {'session_id': TEXT}, ['session_id'], read_only=False),
    tool('curate_library', 'Queue consolidation, preserving evidence and support files.', {'scope': SCOPE}, read_only=False),
    tool('proposal_preview', 'Validate proposed changes against an existing job’s evidence and show their diff, without writing skills.', PROPOSALS, ['job_id', 'proposals']),
    tool('stage_skill', 'Validate and stage a batch for an existing episode. The worker applies it later; report staging only.', PROPOSALS, ['job_id', 'proposals'], read_only=False),
    tool('library_restore', 'Restore after explicit user request; expected_hash protects newer changes.',
         NAME | {'version': {'type': 'integer', 'minimum': 1}, 'expected_hash': TEXT}, ['name', 'version', 'expected_hash'], read_only=False),
    tool('library_pin', 'Pin or unpin after user request; pins prevent automatic retirement.', NAME | {'enabled': {'type': 'boolean'}}, ['name', 'enabled'], read_only=False),
    tool('library_feedback', 'Record uses, views, or explicit user-confirmed helpfulness. Loading is not outcome success.',
         NAME | {'kind': {'type': 'string', 'enum': ['uses', 'views', 'helpful']}}, ['name', 'kind'], read_only=False),
]


class Server:
    def __init__(self, runtime, *, require_context=False):
        self.rt = runtime
        self.require_context = require_context
        self.tools = []
        for spec in TOOLS:
            schema = spec['inputSchema']
            self.tools.append(spec | {'inputSchema': schema | {
                'properties': schema['properties'] | {'context_token': TEXT},
                'required': schema['required'] + (['context_token'] if require_context else [])}})

    def _runtime(self, args):
        rt = self.rt
        token = args.get('context_token')
        if token:
            with self.rt.lib.connect() as db:
                context = db.execute('SELECT * FROM contexts WHERE token=?', (token,)).fetchone()
            if not context:
                raise Rejected('Unknown hook context. Start a trusted plugin session first.')
            rt = Runtime(replace(self.rt.settings, cwd=Path(context['cwd'])), scope=context['scope'])
            rt.context_session = context['session']
        elif self.require_context:
            raise Rejected('Installed MCP calls require the current hook context_token.')
        scope = args.get('scope', 'project')
        if scope not in ('project', 'global'):
            raise Rejected('Scope must be current project or opt-in global.')
        return Runtime(rt.settings, scope='global') if scope == 'global' else rt

    def _job(self, rt, job_id):
        with rt.lib.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE scope=? AND id=?', (rt.scope, job_id)).fetchone()
        if not row:
            raise Rejected('Job not found in the current project.')
        return dict(row)

    def call(self, name, args):
        spec = next((t for t in self.tools if t['name'] == name), None)
        if spec is None:
            raise Rejected('Unknown tool.')
        if not isinstance(args, dict) or set(args) - set(spec['inputSchema']['properties']) \
                or any(key not in args for key in spec['inputSchema']['required']):
            raise Rejected('Invalid tool arguments.')
        for key, value in args.items():
            field = spec['inputSchema']['properties'][key]
            typ = field.get('type')
            if (typ == 'string' and not isinstance(value, str)) \
                    or (typ == 'boolean' and not isinstance(value, bool)) \
                    or (typ == 'integer' and (type(value) is not int or value < field.get('minimum', 0))) \
                    or (typ == 'array' and not isinstance(value, list)) \
                    or ('enum' in field and value not in field['enum']):
                raise Rejected('Invalid type or value for '+key)
        rt = self._runtime(args)
        lib = rt.lib
        if name == 'library_search':
            return rt.search(args['query'], args.get('limit',5))
        if name == 'library_list':
            return lib.list(include_archived=args.get('include_archived', False))
        if name == 'library_read':
            return lib.read(args['name'], count_view=True)
        if name == 'library_history':
            return lib.history(args['name'])
        if name == 'library_status':
            return rt.status()
        if name == 'library_restore':
            return lib.restore(args['name'], args['version'], args['expected_hash'])
        if name == 'library_pin':
            lib.pin(args['name'], args['enabled'])
            return {'pinned': args['enabled']}
        if name == 'library_feedback':
            lib.feedback(args['name'], args['kind'])
            return {'recorded': args['kind']}
        if name == 'curate_library':
            job = rt.enqueue_curator()
            if job:
                rt.launch()
            return {'queued': bool(job), 'job_id': job}
        if name == 'learn_episode':
            if getattr(rt, 'context_session', args['session_id']) != args['session_id']:
                raise Rejected('Session id does not match this hook context.')
            with lib.connect() as db:
                if args.get('session_id'):
                    row = db.execute('SELECT * FROM session_paths WHERE scope=? AND session=?',
                                     (rt.scope, args['session_id'])).fetchone()
                else:
                    row = db.execute('SELECT * FROM session_paths WHERE scope=? ORDER BY updated DESC LIMIT 1', (rt.scope,)).fetchone()
            if not row:
                raise Rejected('No registered transcript. Run trusted hooks or CLI learn --episode-file.')
            job = rt._capture_job(dict(session_id=row['session'], transcript_path=row['path']))
            if job:
                rt.launch()
            return {'queued': bool(job), 'job_id': job}
        if name in ('proposal_preview', 'stage_skill'):
            job = self._job(rt, args['job_id'])
            if job['status'] not in ('queued', 'proposed', 'rejected'):
                raise Rejected('Job is running or applied; queue a new episode.')
            proposals = args['proposals']
            verdict = lib.preview(proposals, job['evidence'])
            if name == 'proposal_preview':
                diff = []
                for proposal in proposals:
                    try:
                        old = lib.read(proposal['name'])['body']
                    except Rejected:
                        old = ''
                    new = proposal.get('body', old)
                    if proposal['action'] == 'patch':
                        new = old.replace(proposal['old_string'], proposal['new_string'], 1)
                    diff.extend(difflib.unified_diff(old.splitlines(), str(new).splitlines(),
                                                    fromfile=proposal['name']+'/before', tofile=proposal['name']+'/after'))
                return {'validation': verdict, 'diff': '\n'.join(diff), 'proposals': proposals}
            with lib.transaction() as db:
                changed = db.execute("UPDATE jobs SET status='proposed',result=?,error='' WHERE id=? AND scope=? AND status IN ('queued','proposed','rejected')",
                                     (json.dumps(proposals), job['id'], lib.scope)).rowcount
                if not changed:
                    raise Rejected('Job changed while staging.')
            rt.launch()
            return {'status': 'proposed', 'job_id': job['id'], 'count': len(proposals)}
        raise Rejected('Unknown tool.')

    def handle(self, request):
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in request:
            return None
        rid, method, params = request['id'], request['method'], request.get('params', {})
        reply = {'jsonrpc': '2.0', 'id': rid}
        if method == 'initialize':
            version = params.get('protocolVersion', '2024-11-05') if isinstance(params, dict) else '2024-11-05'
            reply['result'] = {'protocolVersion': version, 'capabilities': {'tools': {}},
                               'serverInfo': {'name': 'autoharness-codex', 'version': __version__}}
        elif method == 'ping':
            reply['result'] = {}
        elif method == 'tools/list':
            reply['result'] = {'tools': self.tools}
        elif method == 'tools/call':
            try:
                if not isinstance(params, dict):
                    raise Rejected('Invalid params.')
                value = self.call(params.get('name'), params.get('arguments', {}))
                reply['result'] = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
            except (Rejected, KeyError, TypeError, OSError) as exc:
                reply['result'] = {'isError': True, 'content': [{'type': 'text', 'text': redact(str(exc))[:2000]}]}
        else:
            reply['error'] = {'code': -32601, 'message': 'Method not found'}
        return reply


def serve(server, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    while True:
        line = stdin.readline(512_001)
        if not line:
            break
        try:
            if len(line) > 512_000:
                while line and not line.endswith('\n'):
                    line = stdin.readline(4096)
                raise ValueError('Oversized message')
            response = server.handle(json.loads(line))
        except (ValueError, TypeError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False)+'\n')
            stdout.flush()
