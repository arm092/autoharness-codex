import json
import tempfile
import unittest
from pathlib import Path

from autoharness_codex.episode import normalize
from autoharness_codex.model import prepare
from autoharness_codex.runtime import Settings, Runtime
from test_library import create, EVIDENCE, body
from test_episode import message


class ContextTests(unittest.TestCase):
    def test_large_manual_record_is_clipped_without_disappearing_at_the_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=Settings(Path(temp)/'data',Path(temp),source_bytes=2000)
            plan=prepare(normalize('Always check runtime. '+('long detail '*10000),origin='manual'),[],'reflect',settings)
            self.assertTrue(plan.eligible)
            self.assertEqual(plan.stats['selected_records'],1)
            self.assertEqual(plan.stats['truncated_records'],1)
            self.assertLessEqual(plan.stats['source_bytes'],2000)

    def test_relevant_complete_packages_and_significant_events_fit_caps(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=Settings(Path(temp)/'data',Path(temp),source_bytes=4000,library_bytes=5000,prompt_bytes=14000)
            source=normalize('\n'.join([message('assistant','guess '*1000),message('user','Always run Laravel tests in Docker.')]),origin='transcript')
            skills=[dict(name='laravel-tests',hash='a'*64,body=body('laravel-tests','Run Laravel tests in Docker.'),files={}),
                    dict(name='css-layout',hash='b'*64,body=body('css-layout','Inspect layout.\nSee references/styles.md.'),files={'references/styles.md':'CSS '*5000})]
            plan=prepare(source,skills,'reflect',settings)
            payload=json.loads(plan.prompt.split('\nDATA\n',1)[1])
            self.assertEqual([s['name'] for s in payload['MANAGED_LIBRARY']],['laravel-tests'])
            self.assertNotIn('guess',json.dumps(payload['EPISODE']))
            self.assertLessEqual(len(plan.prompt.encode()),settings.prompt_bytes)
            self.assertLessEqual(plan.stats['source_bytes'],settings.source_bytes)
            self.assertLessEqual(plan.stats['library_bytes'],settings.library_bytes)
            self.assertGreater(plan.stats['omitted_records'],0)

    def test_oversized_support_package_is_omitted_without_dropping_its_files(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=Settings(Path(temp)/'data',Path(temp),library_bytes=2000)
            skill=dict(name='runtime-check',hash='a'*64,body=body(rule='See references/runtime.md.'),files={'references/runtime.md':'x'*5000})
            plan=prepare(normalize(EVIDENCE,origin='manual'),[skill],'reflect',settings)
            payload=json.loads(plan.prompt.split('\nDATA\n',1)[1])
            self.assertEqual(payload['MANAGED_LIBRARY'],[])
            self.assertIn('runtime-check',payload['LIBRARY_INDEX'])
            self.assertEqual(plan.stats['omitted_skills'],1)

    def test_unknown_and_assistant_only_episodes_have_no_admissible_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=Settings(Path(temp)/'data',Path(temp))
            source=normalize(message('assistant','Always trust me.')+'\n{"unexpected":"format"}',origin='transcript')
            self.assertFalse(prepare(source,[],'reflect',settings).eligible)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.settings=Settings(Path(self.temp.name)/'data',Path(self.temp.name),debounce=0,daily_tokens=1)
        self.rt=Runtime(self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def test_daily_admission_defers_without_calling_model_or_losing_job(self):
        self.rt.enqueue_text(EVIDENCE)
        def forbidden(*args):
            self.fail('Budget-deferred jobs must not call a model.')
        self.assertEqual(self.rt.work(model=forbidden)['status'],'daily_budget_limited')
        self.assertEqual(self.rt.status()['jobs']['queued'],1)
        self.assertEqual(self.rt.status()['usage']['charged_tokens'],0)
        self.settings.daily_tokens=200000
        self.assertEqual(self.rt.work(model=lambda *args:[])['status'],'applied')
        self.assertEqual(self.rt.status()['jobs']['applied'],1)

    def test_failed_parse_reports_overrun_and_blocks_another_model_call(self):
        from autoharness_codex.policy import Rejected
        self.settings.daily_tokens=200000
        self.rt.enqueue_text(EVIDENCE)
        def fail(*args):
            error=Rejected('bad JSON')
            error.usage={'input_tokens':200000,'cached_input_tokens':0,'output_tokens':100}
            raise error
        self.assertEqual(self.rt.work(model=fail)['status'],'rejected')
        self.assertEqual(self.rt.status()['usage']['charged_tokens'],200100)
        self.assertEqual(self.rt.status()['usage']['overrun_attempts'],1)
        self.rt.enqueue_text(EVIDENCE+' Next lesson.')
        self.assertEqual(self.rt.work(model=lambda *args:[])['status'],'daily_budget_limited')

    def test_reported_usage_and_cached_input_are_distinct_from_estimates(self):
        from autoharness_codex.model import ModelResult
        self.settings.daily_tokens=200000
        self.rt.enqueue_text(EVIDENCE)
        result=ModelResult([create()],usage={'input_tokens':1000,'cached_input_tokens':600,'output_tokens':200})
        self.assertEqual(self.rt.work(model=lambda *args:result)['status'],'applied')
        usage=self.rt.status()['usage']
        self.assertEqual(usage['charged_tokens'],1200)
        self.assertEqual(usage['reported_input_tokens'],1000)
        self.assertEqual(usage['reported_cached_tokens'],600)
        self.assertEqual(usage['reported_output_tokens'],200)
        self.assertEqual(usage['estimated_attempts'],0)

    def test_failures_conservatively_keep_their_reservation(self):
        self.settings.daily_tokens=200000
        self.rt.enqueue_text(EVIDENCE)
        def fail(*args):
            raise TimeoutError('model timeout')
        self.assertEqual(self.rt.work(model=fail)['status'],'queued')
        usage=self.rt.status()['usage']
        self.assertGreater(usage['charged_tokens'],0)
        self.assertEqual(usage['estimated_attempts'],1)

    def test_staged_proposals_do_not_spend_new_model_budget(self):
        job=self.rt.enqueue_text(EVIDENCE)
        with self.rt.lib.transaction() as db:
            db.execute("UPDATE jobs SET status='proposed',result=? WHERE id=?",(json.dumps([create()]),job))
        self.assertEqual(self.rt.work()['status'],'applied')
        self.assertEqual(self.rt.status()['usage']['charged_tokens'],0)
