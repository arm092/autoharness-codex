import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from autoharness_codex.library import Library, Conflict, Rejected


EVIDENCE = 'User: Always check the active runtime before running tests.'


def body(name='runtime-check', rule='Check the active runtime before running tests.'):
    return f'---\nname: {name}\ndescription: Use when running application tests.\ncategory: testing\n---\n{rule}\n'


def create(name='runtime-check', text=None):
    return dict(action='create', name=name, body=text or body(name), files={},
                reason='User corrected the testing workflow.', evidence=EVIDENCE)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'data'
        self.lib = Library(self.root, 'project:test')

    def tearDown(self):
        self.temp.cleanup()

    def test_create_evidence_idempotence_and_immutable_history(self):
        first = self.lib.apply([create()], EVIDENCE, 'episode-1')
        self.assertEqual(first, self.lib.apply([create()], EVIDENCE, 'episode-1'))
        skill = self.lib.read('runtime-check')
        self.assertEqual(skill['body'], body())
        self.assertTrue(Path(skill['path']).is_file())
        self.assertEqual(len(self.lib.history('runtime-check')), 1)
        proposal = dict(action='patch', name=skill['name'], expected_hash=skill['hash'],
                        old_string='Check the active runtime', new_string='Verify the active runtime',
                        evidence=EVIDENCE, reason='Clarify the directive.')
        self.lib.apply([proposal], EVIDENCE, 'episode-2')
        self.assertIn('Verify', self.lib.read(skill['name'])['body'])
        self.assertEqual(len(self.lib.history(skill['name'])), 2)
        self.assertIn('Check', Path(skill['path']).read_text(encoding='utf-8'))

    def test_fabricated_evidence_and_unowned_updates_are_rejected(self):
        bad = create()
        bad['evidence'] = 'An invented quote.'
        with self.assertRaises(Rejected):
            self.lib.apply([bad], EVIDENCE, 'fake')
        with self.assertRaises(Conflict):
            self.lib.apply([dict(action='update', name='user-skill', expected_hash='abc',
                                 body=body('user-skill'), reason='change', evidence=EVIDENCE)], EVIDENCE, 'unowned')
        self.assertEqual(self.lib.list(), [])

    def test_atomic_merge_preserves_both_on_stale_or_failed_transfer(self):
        self.lib.apply([create('umbrella'), create('narrow')], EVIDENCE, 'initial')
        umbrella, narrow = self.lib.read('umbrella'), self.lib.read('narrow')
        merge = [dict(action='update', name='umbrella', expected_hash=umbrella['hash'],
                      body=body('umbrella', 'Check runtime and verify dependencies.'), files={},
                      reason='Absorb narrow knowledge.', evidence=EVIDENCE),
                 dict(action='archive', name='narrow', expected_hash='stale', absorbed_into='umbrella',
                      reason='Merged.', evidence=EVIDENCE)]
        with self.assertRaises(Conflict):
            self.lib.apply(merge, EVIDENCE, 'failed-merge')
        self.assertEqual(self.lib.read('umbrella')['hash'], umbrella['hash'])
        self.assertEqual(self.lib.read('narrow')['hash'], narrow['hash'])
        merge[1]['expected_hash'] = narrow['hash']
        self.lib.apply(merge, EVIDENCE, 'merge')
        self.assertEqual([s['name'] for s in self.lib.list()], ['umbrella'])
        self.assertEqual(self.lib.read('narrow', include_archived=True)['status'], 'archived')

    def test_restore_requires_current_hash_and_keeps_newer_versions(self):
        self.lib.apply([create()], EVIDENCE, 'create')
        old = self.lib.read('runtime-check')
        self.lib.apply([dict(action='update', name=old['name'], expected_hash=old['hash'],
                             body=body(rule='Use the actual runtime.'), files={},
                             reason='refine', evidence=EVIDENCE)], EVIDENCE, 'update')
        new = self.lib.read(old['name'])
        with self.assertRaises(Conflict):
            self.lib.restore(old['name'], 1, old['hash'])
        self.lib.restore(old['name'], 1, new['hash'])
        self.assertEqual(self.lib.read(old['name'])['body'], old['body'])
        self.assertEqual(len(self.lib.history(old['name'])), 3)

    def test_path_scripts_secret_and_global_boundaries(self):
        for path in ['../escape', 'references/../../escape', 'references/con.txt', 'references/x\\y.txt']:
            proposal = create()
            proposal['files'] = {path: 'test'}
            with self.subTest(path=path), self.assertRaises(Rejected):
                self.lib.apply([proposal], EVIDENCE, path)
        proposal = create(text=body(rule='See scripts/check.py.'))
        proposal['files'] = {'scripts/check.py': 'print("ok")'}
        with self.assertRaises(Rejected):
            self.lib.apply([proposal], EVIDENCE, 'script')
        proposal = create(text=body(rule='token=ghp_' + 'a' * 30))
        with self.assertRaises(Rejected):
            self.lib.apply([proposal], EVIDENCE, 'secret')
        global_lib = Library(self.root, 'global')
        with self.assertRaises(Rejected):
            global_lib.apply([create(text=body(rule='Read C:/project/file.php.'))], EVIDENCE, 'global')

    def test_parallel_stale_writers_cannot_overwrite_newer_revision(self):
        self.lib.apply([create()], EVIDENCE, 'create')
        old = self.lib.read('runtime-check')
        def change(n):
            proposal = dict(action='update', name=old['name'], expected_hash=old['hash'],
                            body=body(rule=f'Check runtime {n}.'), files={}, reason='refine', evidence=EVIDENCE)
            try:
                Library(self.root, 'project:test').apply([proposal], EVIDENCE, f'writer-{n}')
                return 'ok'
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(change, [1, 2])), ['ok', 'conflict'])

    def test_scope_isolation_and_pins(self):
        self.lib.apply([create()], EVIDENCE, 'create')
        self.assertEqual(Library(self.root, 'project:other').list(), [])
        self.lib.pin('runtime-check', True)
        self.assertEqual(self.lib.retire_unused(500, maturity=100, capacity=1), [])
        skill = self.lib.read('runtime-check')
        with self.assertRaises(Rejected):
            self.lib.apply([dict(action='archive', name=skill['name'], expected_hash=skill['hash'],
                                 reason='Automatic retirement', evidence=EVIDENCE)], EVIDENCE, 'pinned-archive')

    def test_symlink_data_root_is_refused(self):
        link = Path(self.temp.name) / 'link'
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation requires OS privileges.')
        with self.assertRaises(Rejected):
            Library(link, 'project:test')

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS root-owned OS alias')
    def test_macos_system_var_alias_is_canonicalized_without_allowing_user_links(self):
        canonical = Path(self.temp.name).resolve()
        if not canonical.is_relative_to('/private/var'):
            self.skipTest('Temporary directory is outside the macOS var alias.')
        aliased = Path('/var')/canonical.relative_to('/private/var')/'os-alias-data'
        library = Library(aliased, 'project:mac-os-alias')
        self.assertEqual(library.root, aliased.resolve())
        link = canonical/'user-link'
        link.symlink_to(library.root, target_is_directory=True)
        with self.assertRaises(Rejected):
            Library(Path('/var')/link.relative_to('/private/var'), 'project:unsafe-link')


if __name__ == '__main__':
    unittest.main()
