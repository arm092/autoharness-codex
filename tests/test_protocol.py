import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from autoharness_codex.mcp import Server, serve
from autoharness_codex.runtime import Settings, Runtime
from test_library import EVIDENCE, create


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rt = Runtime(Settings(Path(self.temp.name)/'data', Path(self.temp.name), auto=False))
        self.server = Server(self.rt)

    def tearDown(self):
        self.temp.cleanup()

    def request(self, method, params=None, rid=1):
        return self.server.handle(dict(jsonrpc='2.0', id=rid, method=method, params=params or {}))

    def call(self, name, args):
        return self.request('tools/call', dict(name=name, arguments=args))['result']

    def test_initialize_notifications_unknown_method_and_malformed_request(self):
        self.assertIn('serverInfo', self.request('initialize', {'protocolVersion': '2024-11-05'})['result'])
        self.assertIsNone(self.server.handle(dict(jsonrpc='2.0', method='notifications/initialized')))
        self.assertEqual(self.request('unknown')['error']['code'], -32601)
        self.assertEqual(self.server.handle([])['error']['code'], -32600)
        sink = io.StringIO()
        serve(self.server, io.StringIO('{bad}\n'+json.dumps(dict(jsonrpc='2.0', id=2, method='ping'))+'\n'), sink)
        replies = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(replies[0]['error']['code'], -32700)
        self.assertEqual(replies[1]['id'], 2)

    def test_read_list_and_restore_are_scope_bound_and_validated(self):
        self.rt.lib.apply([create()], EVIDENCE, 'setup')
        data = self.call('library_read', {'name': 'runtime-check'})
        self.assertFalse(data.get('isError', False))
        self.assertIn('Check the active runtime', data['content'][0]['text'])
        self.assertEqual(self.rt.lib.read('runtime-check')['views'], 1)
        self.assertTrue(self.call('library_read', {'name': '../escape'})['isError'])
        self.assertTrue(self.call('library_read', {'name': 'runtime-check', 'scope': 'project:other'})['isError'])
        self.assertTrue(self.call('library_feedback', {'name': 'runtime-check', 'kind': 'outcome-success'})['isError'])

    def test_queue_cannot_apply_fabricated_evidence_and_proposal_diff_is_reviewable(self):
        job = self.rt.enqueue_text(EVIDENCE)
        bad = create() | dict(evidence='Fabricated quote')
        result = self.call('stage_skill', {'job_id': job, 'proposals': [bad]})
        self.assertTrue(result['isError'])
        preview = self.call('proposal_preview', {'job_id': job, 'proposals': [create()]})
        self.assertIn('runtime-check', preview['content'][0]['text'])
        self.assertEqual(self.rt.lib.list(), [])
        with patch.object(Runtime, 'launch'):
            result = self.call('stage_skill', {'job_id': job, 'proposals': [create()]})
        self.assertFalse(result.get('isError', False))
        self.assertEqual(self.rt.lib.list(), [])
        self.assertEqual(self.rt.work()['status'], 'applied')
        self.assertEqual(self.rt.lib.read('runtime-check')['name'], 'runtime-check')

    def test_installed_server_requires_a_hook_context_not_its_plugin_directory(self):
        event = dict(hook_event_name='SessionStart', cwd=str(self.rt.settings.cwd), session_id='current-session')
        context = self.rt.dispatch(event, launch=lambda: None)
        token = context['hookSpecificOutput']['additionalContext'].split('context_token: ')[1].splitlines()[0]
        server = Server(Runtime(Settings(self.rt.settings.data, self.rt.settings.data/'installed-plugin', auto=False)), require_context=True)
        self.assertTrue(server.handle(dict(jsonrpc='2.0', id=1, method='tools/call',
                        params=dict(name='library_list', arguments={})))['result']['isError'])
        self.rt.lib.apply([create()], EVIDENCE, 'setup')
        reply = server.handle(dict(jsonrpc='2.0', id=2, method='tools/call',
                              params=dict(name='library_list', arguments={'context_token': token})))
        self.assertIn('runtime-check', reply['result']['content'][0]['text'])
        bad = server.handle(dict(jsonrpc='2.0', id=3, method='tools/call',
                            params=dict(name='library_list', arguments={'context_token': 'fabricated'})))
        self.assertTrue(bad['result']['isError'])


if __name__ == '__main__':
    unittest.main()
