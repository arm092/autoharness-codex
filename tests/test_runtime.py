import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autoharness_codex.capture import capture
from autoharness_codex.runtime import Settings, Runtime
from autoharness_codex.library import Library
from autoharness_codex.policy import redact
from test_library import EVIDENCE, create


class CaptureTests(unittest.TestCase):
    def test_append_partial_utf8_redaction_and_file_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace.jsonl'
            line = json.dumps({'type': 'user', 'message': 'Проверь runtime token=ghp_' + 'a'*30}, ensure_ascii=False)
            path.write_bytes((line+'\nunfinished').encode('utf-8'))
            text, mark = capture(path, {})
            self.assertIn('Проверь', text)
            self.assertNotIn('ghp_', text)
            self.assertNotIn('unfinished', text)
            with path.open('ab') as handle:
                handle.write(b' complete\n')
            tail, mark2 = capture(path, mark)
            self.assertEqual(tail, 'unfinished complete')
            self.assertEqual(capture(path, mark2)[0], '')
            path.write_text('replacement\n', encoding='utf-8')
            self.assertEqual(capture(path, mark2)[0], 'replacement')

    def test_capture_bounds_huge_records_and_window(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trace'
            path.write_bytes((('x'*100_000+'\n')*10).encode())
            text, _ = capture(path, {}, record_cap=100, window_cap=250)
            self.assertLessEqual(len(text.encode()), 250)

    def test_pem_escaped_clipped_and_split_records_do_not_expose_key_bodies(self):
        begin, finish = '-----BEGIN PRIVATE KEY-----', '-----END PRIVATE KEY-----'
        key = begin+'\nSYNTHETIC_KEY_BODY\n'+finish
        for text in [key, begin+'\nSYNTHETIC_KEY_BODY']:
            self.assertNotIn('SYNTHETIC_KEY_BODY', redact(text))
            self.assertEqual(redact(redact(text)), redact(text))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'trace.jsonl'
            for value in [json.dumps({'text':key,'after':'retain ordinary context'}),
                          json.dumps({'text':key}).replace('SYNTHETIC', '\\u0053YNTHETIC')]:
                path.write_text(value+'\n', encoding='utf-8')
                text, _ = capture(path, {})
                self.assertNotIn('KEY_BODY', text)
                self.assertIn('REDACTED', text)
            path.write_text(json.dumps({'text':key,'after':'retain ordinary context'})+'\n', encoding='utf-8')
            self.assertEqual(json.loads(capture(path, {})[0])['after'], 'retain ordinary context')
            path.write_text(json.dumps({'content':[{'text':begin}, {'text':'SYNTHETIC_KEY_BODY'},
                                                   {'text':finish}], 'after':'retain context'})+'\n', encoding='utf-8')
            text, _ = capture(path, {})
            self.assertNotIn('KEY_BODY', text)
            self.assertEqual(json.loads(text)['after'], 'retain context')
            path.write_text('x'*5000+begin+'\n', encoding='utf-8')
            text, mark = capture(path, {}, record_cap=80)
            self.assertTrue(mark['pem_open'])
            with path.open('a', encoding='utf-8') as handle:
                handle.write('SYNTHETIC_KEY_BODY\n'+finish+'\nordinary\n')
            text, mark = capture(path, mark, record_cap=80)
            self.assertNotIn('KEY_BODY', text)
            self.assertIn('ordinary', text)
            self.assertFalse(mark['pem_open'])
            escaped_begin = ''.join('\\u%04x' % ord(c) for c in begin)
            path.write_text('{"text":"'+escaped_begin+'"}\n', encoding='utf-8')
            _, mark = capture(path, {})
            self.assertTrue(mark['pem_open'])
            with path.open('a', encoding='utf-8') as handle:
                handle.write('{"text":"SYNTHETIC_KEY_BODY"}\n'+finish+'\n')
            self.assertNotIn('KEY_BODY', capture(path, mark)[0])
            path.write_text(json.dumps({'text':'prefix '+key+'x'*5000})+'\n', encoding='utf-8')
            self.assertNotIn('KEY_BODY', capture(path, {}, record_cap=120)[0])
            path.write_text(begin+'\nPARTIAL_KEY', encoding='utf-8')
            _, mark = capture(path, {})
            with path.open('a', encoding='utf-8') as handle:
                handle.write('_BODY\n'+finish+'\n')
            self.assertNotIn('PARTIAL_KEY', capture(path, mark)[0])

    def test_card_validation_retains_noncard_identifiers_and_redaction_is_idempotent(self):
        cards = ['4111 1111 1111 1111', '5555-5555-5555-4444', '378282246310005']
        negatives = ['1700000000000', '1234567890123456', '4111111111111112',
                     'row_4111111111111111', 'order=9999999999999999']
        for value in cards:
            self.assertEqual(redact(value), '[REDACTED:personal]')
        for value in negatives:
            self.assertEqual(redact(value), value)
        text = 'token=ghp_'+'a'*30+' '+cards[0]+' -----BEGIN PRIVATE KEY-----\nBODY'
        self.assertEqual(redact(redact(text)), redact(text))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.settings = Settings(self.path/'data', self.path/'project', cadence=2, debounce=0)
        self.rt = Runtime(self.settings)
        self.trace = self.path/'trace.jsonl'
        self.trace.write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'user',
                             'content':[{'type':'input_text','text':EVIDENCE}]}})+'\n', encoding='utf-8')
        self.event = dict(session_id='s1', cwd=str(self.settings.cwd), transcript_path=str(self.trace))

    def tearDown(self):
        self.temp.cleanup()

    def event_call(self, event_name, **kw):
        return self.rt.dispatch(self.event | dict(hook_event_name=event_name) | kw, launch=lambda: None)

    def test_hook_dedup_and_background_queue_apply_then_recall(self):
        self.event_call('PostToolUse', tool_use_id='t1')
        self.event_call('PostToolUse', tool_use_id='t1')
        self.assertEqual(self.event_call('Stop', turn_id='a')['queued'], 0)
        self.event_call('PostToolUse', tool_use_id='t2')
        self.assertEqual(self.event_call('Stop', turn_id='b')['queued'], 1)
        self.assertEqual(self.event_call('Stop', turn_id='b')['queued'], 0)
        result = self.rt.work(model=lambda source, skills, kind: [create()])
        self.assertEqual(result['status'], 'applied')
        index = self.event_call('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('runtime-check', index)
        self.assertEqual(self.rt.lib.counter('turns'), 2)
        self.assertEqual(self.rt.status()['jobs']['applied'], 1)

    def test_failure_keeps_evidence_and_retries_without_advancing_confirmed_watermark(self):
        self.event_call('SessionEnd')
        def fail(*args):
            raise TimeoutError('model timed out')
        result = self.rt.work(model=fail)
        self.assertEqual(result['status'], 'queued')
        with self.rt.lib.connect() as db:
            session = db.execute('SELECT * FROM sessions').fetchone()
            self.assertEqual(json.loads(session['watermark']), {})
            self.assertIn(EVIDENCE, db.execute('SELECT evidence FROM jobs').fetchone()[0])
        self.assertEqual(self.rt.work(model=lambda *args: [create()])['status'], 'applied')

    def test_child_recursion_and_interrupt_do_not_learn(self):
        with patch.dict('os.environ', {'AUTOHARNESS_CODEX_CHILD': '1'}):
            self.assertEqual(self.event_call('SessionEnd'), {})
        self.event_call('Interrupt')
        self.assertEqual(self.rt.status()['jobs'], {})

    def test_successive_session_end_windows_do_not_lose_tail(self):
        self.event_call('SessionEnd')
        with self.trace.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'type':'response_item','payload':{'type':'message','role':'user',
                         'content':[{'type':'input_text','text':'User: Verify dependency versions too.'}]}})+'\n')
        self.event_call('SessionEnd')
        seen = []
        self.rt.work(model=lambda source, *args: seen.append(source) or [])
        self.rt.work(model=lambda source, *args: seen.append(source) or [])
        self.assertEqual(len(seen), 2)
        self.assertIn('Verify dependency', seen[1])
        self.assertNotIn(EVIDENCE, seen[1])

    def test_hourly_limit_leaves_work_queued(self):
        self.settings.hourly_limit = 1
        self.rt.enqueue_text(EVIDENCE, 'manual')
        self.rt.work(model=lambda *args: [])
        self.rt.enqueue_text(EVIDENCE+' Again.', 'manual')
        self.assertEqual(self.rt.work(model=lambda *args: [])['status'], 'rate_limited')
        self.assertEqual(self.rt.status()['jobs']['queued'], 1)

    def test_curator_has_system_evidence_and_runs_only_with_multiple_skills(self):
        self.rt.lib.apply([create('one'), create('two')], EVIDENCE, 'setup')
        job = self.rt.enqueue_curator()
        self.assertTrue(job)
        self.assertTrue(list((self.settings.data/'snapshots').glob('*.json')))
        self.assertEqual(self.rt.work(model=lambda *args: [])['status'], 'applied')

    def test_crash_after_library_commit_recovers_receipt_without_new_model_call(self):
        job = self.rt.enqueue_text(EVIDENCE)
        self.rt.lib.apply([create()], EVIDENCE, job)
        with self.rt.lib.transaction() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
        def forbidden(*args):
            self.fail('A committed receipt must be recovered without rerunning the model.')
        self.assertEqual(self.rt.work(model=forbidden)['status'], 'applied')
        self.assertEqual(len(self.rt.lib.history('runtime-check')), 1)
        self.assertEqual(self.rt.status()['jobs']['applied'], 1)

    def test_staged_proposals_survive_worker_crash_before_library_commit(self):
        job = self.rt.enqueue_text(EVIDENCE)
        with self.rt.lib.transaction() as db:
            db.execute("UPDATE jobs SET status='running',result=? WHERE id=?", (json.dumps([create()]), job))
        def forbidden(*args):
            self.fail('Staged proposals must not be regenerated after recovery.')
        self.assertEqual(self.rt.work(model=forbidden)['status'], 'applied')
        self.assertEqual(self.rt.lib.read('runtime-check')['name'], 'runtime-check')

    def test_global_worker_preserves_scope(self):
        self.settings.global_enabled = True
        global_rt = Runtime(self.settings, scope='global')
        with patch('subprocess.Popen') as launch:
            global_rt.launch()
            args = launch.call_args.args[0]
            self.assertEqual(args[args.index('--scope')+1], 'global')

    def test_opt_in_global_retirement_counts_main_replies_without_duplicates(self):
        self.settings.global_enabled = True
        self.event_call('Stop', turn_id='once')
        self.event_call('Stop', turn_id='once')
        global_lib = Library(self.settings.data, 'global')
        self.assertEqual(global_lib.counter('turns'), 1)
        global_lib.apply([create()], EVIDENCE, 'global-create')
        with global_lib.transaction() as db:
            db.execute("UPDATE counters SET value=301 WHERE scope='global' AND key='turns'")
        self.settings.retire = True
        self.event_call('SessionStart')
        self.assertEqual(global_lib.list(), [])


if __name__ == '__main__':
    unittest.main()
