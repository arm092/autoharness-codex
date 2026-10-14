"""Native macOS runtime and actual Codex registration smoke; no model calls or GUI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import time
import urllib.request

CODEX_DIGESTS = {'arm64': 'b293a0fcdd871900a44c0a4f40a1aa401b31e02854f790ebdb8bd5d1177fd1fe',
    'x86_64': 'd68e39d8f62639f33f7d00656554cb9c3ef7809e664a3827e62ab3ace3c21b21'}


def verify(payload):
    payload = Path(payload).resolve()
    python, driver = payload/'plugin/runtime/bin/python3', payload/'plugin/scripts/macos_install.py'
    with tempfile.TemporaryDirectory(prefix="autoharness mac smoke's ") as temp:
        scratch = Path(temp)
        home, project, root = scratch/'profile', scratch/'project', scratch/'installed program'
        home.mkdir()
        env = os.environ | {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'CODEX_HOME': str(home),
            'AUTOHARNESS_CODEX_AUTO': '1'}
        env.pop('AUTOHARNESS_CODEX_CHILD', None)
        target = 'aarch64' if platform.machine() == 'arm64' else 'x86_64'
        archive = scratch/'codex.tar.gz'
        url = f'https://github.com/openai/codex/releases/download/rust-v0.162.1/codex-{target}-apple-darwin.tar.gz'
        with urllib.request.urlopen(url, timeout=120) as response: archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != CODEX_DIGESTS[platform.machine()]:
            raise RuntimeError('Test CLI checksum mismatch.')
        with tarfile.open(archive) as package: package.extractall(scratch/'codex', filter='data')
        binary = next((scratch/'codex').rglob('codex-'+target+'-apple-darwin'))
        def call(args, source=None):
            result = subprocess.run([str(p) for p in args], input=source, env=env,
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            if result.returncode: raise RuntimeError(result.stderr or result.stdout)
            return result.stdout
        state = json.loads(call([python, '-I', driver, 'install', '--payload', payload,
            '--root', root, '--codex', binary, '--codex-home', home]))
        installed = Path(state['plugin'])
        entry = installed/'scripts/entry.py'
        hooks = json.loads((installed/'hooks/hooks.json').read_text())['hooks']
        trace = scratch/'assistant.jsonl'
        trace.write_text(json.dumps(dict(type='response_item', payload=dict(type='message', role='assistant',
            content=[dict(type='output_text', text='Assistant speculation is not durable evidence.')])) )+'\n')
        for name in hooks:
            command = hooks[name][0]['hooks'][0]['command'].replace('${PLUGIN_ROOT}', str(installed))
            event = dict(hook_event_name=name, cwd=str(project), session_id='mac-smoke', transcript_path=str(trace),
                tool_use_id='native-smoke', turn_id='native-turn')
            result = json.loads(call(['/bin/sh', '-c', command], json.dumps(event)))
            if name == 'SessionStart': assert 'context_token:' in result['hookSpecificOutput']['additionalContext']
        for i in range(60):
            status = json.loads(call([python, '-I', entry, '--cwd', project, 'status']))
            if status['jobs'].get('applied'): break
            time.sleep(.1)
        else: raise RuntimeError('Bundled detached worker failed.')
        requests = ''.join(json.dumps(dict(jsonrpc='2.0', id=i, method=method))+'\n'
            for i, method in enumerate(('initialize', 'tools/list')))
        replies = [json.loads(line) for line in call([python, '-I', entry, 'mcp'], requests).splitlines()]
        assert len(replies[1]['result']['tools']) == 12
        # Repair installs a fresh release while leaving older program files recoverable.
        repaired = json.loads(call([python, '-I', driver, 'install', '--payload', payload,
            '--root', root, '--codex', binary, '--codex-home', home]))
        assert repaired['plugin'] != state['plugin'] and installed.exists()
        knowledge = home/'autoharness-codex/library.sqlite3'
        assert knowledge.is_file()
        removed = json.loads(call([python, '-I', driver, 'unregister', '--root', root]))
        assert removed['knowledge_preserved'] and knowledge.is_file()
        print(json.dumps(dict(architecture=platform.machine(), codex=call([binary, '--version']).strip(),
            hooks=5, tools=12, worker='applied', registration=True, repair=True,
            uninstall=True, knowledge_preserved=True, system_python_required=False)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True)
    verify(parser.parse_args().payload)
