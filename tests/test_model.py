import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autoharness_codex.model import reflect, build_command, child_env, doctor
from autoharness_codex.runtime import Settings
from autoharness_codex.policy import Rejected
from test_library import EVIDENCE, create


class ModelTests(unittest.TestCase):
    def test_command_has_no_permission_bypass_and_disables_hooks_tools_plugins(self):
        settings = Settings(Path('data'), Path('.'), codex='codex')
        args = build_command(settings, Path('scratch'), Path('schema.json'), Path('result.json'))
        self.assertIn('read-only', args)
        self.assertIn('--ignore-user-config', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertIn('hooks', args)
        self.assertIn('shell_tool', args)
        self.assertIn('skip_host_skill_discovery', args)

    def test_environment_drops_unrelated_secrets_but_preserves_cli_auth_home(self):
        env = child_env({'PATH': 'bin', 'CODEX_HOME': 'auth', 'CUSTOM_SECRET': 'secret',
                         'OPENAI_API_KEY': 'private', 'HOME': 'home', 'PLUGIN_DATA': 'data'})
        self.assertEqual(env['CODEX_HOME'], 'auth')
        self.assertEqual(env['AUTOHARNESS_CODEX_CHILD'], '1')
        self.assertNotIn('CUSTOM_SECRET', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('PLUGIN_DATA', env)

    def test_model_output_decoded_and_evidence_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp)/'data', Path(temp), codex='codex')
            def run(args, **kwargs):
                out = Path(args[args.index('--output-last-message')+1])
                out.write_text(json.dumps({'proposals': [create() | {'files': []}]}), encoding='utf-8')
                self.assertIn(EVIDENCE, kwargs['input'])
                self.assertEqual(kwargs['timeout'], 180)
                return subprocess.CompletedProcess(args, 0, '', '')
            self.assertEqual(reflect(EVIDENCE, [], 'reflect', settings, run=run), [create()])

    def test_failed_process_and_invalid_output_do_not_look_successful(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp)/'data', Path(temp), codex='codex')
            with self.assertRaises(RuntimeError):
                reflect(EVIDENCE, [], 'reflect', settings,
                        run=lambda *args, **kw: subprocess.CompletedProcess(args, 1, '', 'permission denied'))
            def run(args, **kwargs):
                Path(args[args.index('--output-last-message')+1]).write_text('not json')
                return subprocess.CompletedProcess(args, 0, '', '')
            with self.assertRaises(Rejected):
                reflect(EVIDENCE, [], 'reflect', settings, run=run)


if __name__ == '__main__':
    unittest.main()
