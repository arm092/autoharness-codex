"""Exercise a built Windows payload without system Python or a model call."""
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def verify(root):
    plugin = Path(root).resolve()/'plugin'
    python, entry = plugin/'runtime/python.exe', plugin/'scripts/entry.py'
    with tempfile.TemporaryDirectory(prefix="autoharness smoke's ") as temp:
        scratch = Path(temp)
        system = Path(os.environ['SystemRoot'])
        env = os.environ | {'PATH': os.pathsep.join(str(p) for p in
            (system/'System32', system, system/'System32/WindowsPowerShell/v1.0')),
            'CODEX_HOME': str(scratch/'profile'), 'AUTOHARNESS_CODEX_DATA': str(scratch/'data'),
            'AUTOHARNESS_CODEX_AUTO': '1'}
        env.pop('AUTOHARNESS_CODEX_CHILD', None)
        def call(args, source=None):
            proc = subprocess.run(args, env=env, input=source, capture_output=True,
                text=True, encoding='utf-8', timeout=30)
            if proc.returncode:
                raise RuntimeError(proc.stderr or proc.stdout)
            return proc.stdout
        version = call([str(python), '-c', 'import sys,sqlite3; print(sys.version.split()[0])']).strip()
        hooks = json.loads((plugin/'hooks/hooks.json').read_text(encoding='utf-8'))['hooks']
        trace = scratch/'assistant.jsonl'
        trace.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message',
            'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Speculation is not durable evidence.'}]}})+'\n')
        for name in hooks:
            command = hooks[name][0]['hooks'][0]['commandWindows'].replace('${PLUGIN_ROOT}', str(plugin))
            event = dict(hook_event_name=name, cwd=str(scratch/'project'), session_id='embed-smoke',
                transcript_path=str(trace), tool_use_id='smoke-tool', turn_id='smoke-turn')
            result = json.loads(call([str(system/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                '-NoProfile', '-NonInteractive', '-Command', command], json.dumps(event)))
            if name == 'SessionStart' and 'context_token:' not in result['hookSpecificOutput']['additionalContext']:
                raise RuntimeError('Missing hook project context.')
        for attempt in range(60):
            status = json.loads(call([str(python), str(entry), '--cwd', str(scratch/'project'), 'status']))
            if status['jobs'].get('applied', 0):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Embedded detached worker did not complete the source-less episode.')
        requests = ''.join(json.dumps(dict(jsonrpc='2.0', id=i, method=method))+'\n'
            for i, method in enumerate(('initialize', 'tools/list')))
        responses = [json.loads(line) for line in call([str(python), str(entry), 'mcp'], requests).splitlines()]
        tools = responses[1]['result']['tools']
        if len(tools) != 12:
            raise RuntimeError('Unexpected MCP tool inventory.')
        result = dict(python=version, hooks=len(hooks), tools=len(tools), detached_worker='applied',
            system_python_required=False)
        print(json.dumps(result))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    verify(parser.parse_args().root)
