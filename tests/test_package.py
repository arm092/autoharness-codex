import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_discovery_guard_rejects_empty_skipped_and_failing_suites(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def check():
                return subprocess.run([sys.executable, str(ROOT/'scripts/check_tests.py'),
                                       '--start-dir', str(folder)], capture_output=True, text=True)
            empty = check()
            self.assertNotEqual(empty.returncode, 0)
            self.assertIn('Collected 0', empty.stdout)
            path = folder/'test_sample.py'
            for assertion, decorator, expected in [('self.assertTrue(True)', '', 0),
                    ('self.assertTrue(False)', '', 1),
                    ('self.assertTrue(True)', '@unittest.skip("fixture skip")\n', 1)]:
                path.write_text('import unittest\n'+decorator+'class Sample(unittest.TestCase):\n'
                                '    def test_sample(self):\n        '+assertion+'\n', encoding='utf-8')
                # Each child must import the fresh same-length fixture, not cached bytecode.
                shutil.rmtree(folder/'__pycache__', ignore_errors=True)
                result = check()
                self.assertEqual(result.returncode, expected, result.stdout+result.stderr)

    def test_entry_hook_uses_event_cwd_and_returns_valid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            data, cwd = Path(temp)/'data', Path(temp)/'project'
            env = os.environ | {'AUTOHARNESS_CODEX_AUTO': '0', 'AUTOHARNESS_CODEX_DATA': str(data)}
            event = dict(hook_event_name='SessionStart', session_id='s', cwd=str(cwd))
            proc = subprocess.run([sys.executable, str(ROOT/'scripts/entry.py'), 'hook'],
                                  input=json.dumps(event), capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['hookEventName'], 'SessionStart')
            proc = subprocess.run([sys.executable, str(ROOT/'scripts/entry.py'), 'hook'],
                                  input='bad json', capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout), {})

    def test_mcp_stdio_handles_initialize_and_list_without_polluting_stdout(self):
        with tempfile.TemporaryDirectory() as temp:
            requests = '\n'.join(json.dumps(dict(jsonrpc='2.0', id=i, method=method))
                                 for i, method in enumerate(['initialize', 'tools/list']))+'\n'
            proc = subprocess.run([sys.executable, str(ROOT/'scripts/entry.py'), '--data', temp, 'mcp'],
                                  input=requests, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            responses = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual(len(responses), 2)
            self.assertIn('stage_skill', [t['name'] for t in responses[1]['result']['tools']])

    def test_prepared_zip_has_native_manifests_and_no_process_or_data_files(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'plugin.zip'
            proc = subprocess.run([sys.executable, str(ROOT/'scripts/package.py'), '--output', str(output)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertIn('.codex-plugin/plugin.json', names)
                self.assertIn('hooks/hooks.json', names)
                self.assertIn('skills/learn/SKILL.md', names)
                self.assertFalse(any('.git/' in n or '__pycache__' in n or n.startswith('work/')
                                     or n.endswith('.sqlite3') for n in names))
                config = json.loads(archive.read('.mcp.json'))
                self.assertEqual(config['mcpServers']['library']['command'], sys.executable)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows-only hook command quoting')
    def test_prepared_windows_hook_executes_from_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as temp:
            output, extracted = Path(temp)/'plugin.zip', Path(temp)/'plugin with spaces'
            build = subprocess.run([sys.executable, str(ROOT/'scripts/package.py'), '--output', str(output)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            with zipfile.ZipFile(output) as archive:
                archive.extractall(extracted)
            hooks = json.loads((extracted/'hooks/hooks.json').read_text())
            command = hooks['hooks']['SessionStart'][0]['hooks'][0]['commandWindows'].replace('${PLUGIN_ROOT}', str(extracted))
            event = dict(hook_event_name='SessionStart', cwd=str(Path(temp)/'project'), session_id='quote-test')
            env = os.environ | {'AUTOHARNESS_CODEX_AUTO': '0', 'AUTOHARNESS_CODEX_DATA': str(Path(temp)/'data')}
            proc = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                  input=json.dumps(event), capture_output=True, text=True, env=env, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('context_token:', json.loads(proc.stdout)['hookSpecificOutput']['additionalContext'])


if __name__ == '__main__':
    unittest.main()
