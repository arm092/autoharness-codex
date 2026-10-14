"""Protect registration ownership and knowledge preservation, without editing real profiles."""
import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_install', ROOT/'scripts/windows_install.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
finish_spec = importlib.util.spec_from_file_location('windows_finish', ROOT/'scripts/windows_finish.py')
finish_driver = importlib.util.module_from_spec(finish_spec)
finish_spec.loader.exec_module(finish_driver)


class FakeCodex:
    def __init__(self, plugin, version='1.2.0'):
        self.plugin, self.version = plugin, version
        self.markets, self.installed, self.calls = [], [], []
        self.fail_add = False

    def __call__(self, binary, home, args):
        self.calls.append(args)
        if args == ['--version']:
            return 'codex-cli 0.159.0'
        if '--help' in args:
            return ' '.join(driver.REQUIRED)
        if args[:3] == ['plugin', 'marketplace', 'list']:
            return json.dumps({'marketplaces': self.markets})
        if args[:2] == ['plugin', 'list']:
            return json.dumps({'installed': self.installed})
        if args[:3] == ['plugin', 'marketplace', 'add']:
            if not any(m['name'] == driver.MARKETPLACE for m in self.markets):
                self.markets.append({'name': driver.MARKETPLACE, 'root': str(self.plugin)})
        elif args[:2] == ['plugin', 'add']:
            if self.fail_add:
                raise RuntimeError('installation refused')
            self.installed = [{'pluginId': driver.PLUGIN, 'installed': True, 'version': self.version}]
        elif args[:2] == ['plugin', 'remove']:
            self.installed = []
        elif args[:3] == ['plugin', 'marketplace', 'remove']:
            self.markets = [m for m in self.markets if m['name'] != args[3]]
        return '{}'


class WindowsInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"installed with space's"
        self.plugin = self.root/'plugin'
        (self.plugin/'.codex-plugin').mkdir(parents=True)
        (self.plugin/'.codex-plugin/plugin.json').write_text(json.dumps({'version': '1.2.0'}))
        (self.plugin/'runtime').mkdir()
        (self.plugin/'runtime/python.exe').touch()
        (self.plugin/'.mcp.json').write_text(json.dumps({'mcpServers': {'library': {'command': 'python'}}}))
        self.binary = Path(self.temp.name)/'codex.exe'
        self.binary.touch()
        self.home = Path(self.temp.name)/'codex profile'
        (self.home/'autoharness-codex').mkdir(parents=True)
        self.knowledge = self.home/'autoharness-codex/library.sqlite3'
        self.knowledge.write_bytes(b'valuable knowledge')
        self.run = FakeCodex(self.plugin)

    def test_registration_repair_uninstall_preserve_knowledge_and_other_marketplaces(self):
        self.run.markets = [{'name': 'other-plugin', 'root': '/another/folder'}]
        result = driver.register(self.root, self.binary, self.home, self.run)
        self.assertTrue(result['registered'])
        mcp = json.loads((self.plugin/'.mcp.json').read_text())
        executable = Path(mcp['mcpServers']['library']['command'])
        self.assertTrue(executable.is_absolute())
        self.assertTrue(executable.samefile(self.plugin/'runtime/python.exe'))
        driver.register(self.root, self.binary, self.home, self.run)
        self.assertTrue(driver.unregister(self.root, self.run)['knowledge_preserved'])
        self.assertEqual(self.knowledge.read_bytes(), b'valuable knowledge')
        self.assertEqual(self.run.markets, [{'name': 'other-plugin', 'root': '/another/folder'}])
        self.assertEqual(driver.unregister(self.root, self.run)['status'], 'not_registered')

    def test_foreign_marketplace_blocks_install_and_uninstall_without_mutation(self):
        self.run.markets = [{'name': driver.MARKETPLACE, 'root': '/foreign/folder'}]
        with self.assertRaisesRegex(ValueError, 'different folder'):
            driver.register(self.root, self.binary, self.home, self.run)
        self.assertFalse((self.root/'install-state.json').exists())
        self.assertFalse(any('add' in c or 'remove' in c for c in self.run.calls if '--help' not in c))
        self.run.markets = []
        driver.register(self.root, self.binary, self.home, self.run)
        self.run.markets = [{'name': driver.MARKETPLACE, 'root': '/foreign/folder'}]
        self.run.calls.clear()
        with self.assertRaises(ValueError):
            driver.unregister(self.root, self.run)
        self.assertFalse(any('remove' in c for c in self.run.calls))

    def test_failed_registration_is_not_reported_as_installed_and_can_be_removed(self):
        self.run.fail_add = True
        with self.assertRaises(RuntimeError):
            driver.register(self.root, self.binary, self.home, self.run)
        self.assertFalse(json.loads((self.root/'install-state.json').read_text())['registered'])
        driver.unregister(self.root, self.run)
        self.assertEqual(self.knowledge.read_bytes(), b'valuable knowledge')

    def test_update_cannot_move_registration_to_another_profile(self):
        driver.register(self.root, self.binary, self.home, self.run)
        self.run.calls.clear()
        with self.assertRaisesRegex(ValueError, 'original folder'):
            driver.register(self.root, self.binary, self.home/'other', self.run)
        self.assertFalse(any('add' in c for c in self.run.calls if '--help' not in c))

    def test_uninstall_preflight_is_read_only_so_canceling_keeps_registration(self):
        driver.register(self.root, self.binary, self.home, self.run)
        self.run.calls.clear()
        state = (self.root/'install-state.json').read_bytes()
        self.assertTrue(driver.uninstall_state(self.root, self.run)['registered'])
        self.assertFalse(any('add' in c or 'remove' in c for c in self.run.calls))
        self.assertEqual((self.root/'install-state.json').read_bytes(), state)
        self.assertTrue(self.run.installed[0]['installed'])


class WindowsFinishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"installed программа's"
        self.root.mkdir()
        self.home = Path(self.temp.name)/'.codex'
        user_home = patch.object(finish_driver.Path, 'home', return_value=Path(self.temp.name))
        user_home.start()
        self.addCleanup(user_home.stop)
        (self.root/'install-state.json').write_text(json.dumps(dict(registered=True,
            plugin=str(self.root/'plugin'), home=str(self.home))), encoding='utf-8')
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_checked_restart_waits_for_shutdown_then_opens_encoded_plugin_page(self):
        calls = []
        running = [object()]
        def shutdown(items):
            self.assertEqual(items, running)
            calls.append('shutdown')
            running.clear()
        def launch(url):
            calls.append(url)
        finish_driver.finish(self.root, True, True, locate=lambda: 'desktop.exe',
            processes=lambda exe: list(running), shutdown=shutdown, launch=launch)
        self.assertEqual(calls[0], 'shutdown')
        self.assertTrue(calls[1].startswith('codex://plugins/autoharness-codex?marketplacePath='))
        self.assertNotIn(' ', calls[1])
        self.assertNotIn("'", calls[1])

    def test_unchecked_options_do_not_close_or_launch_anything(self):
        locate, launch = Mock(), Mock()
        self.assertEqual(finish_driver.finish(self.root, False, False, locate=locate, launch=launch)['status'], 'skipped')
        locate.assert_not_called()
        launch.assert_not_called()

    def test_open_without_restart_never_requests_shutdown(self):
        locate, shutdown, launch = Mock(), Mock(), Mock()
        finish_driver.finish(self.root, False, True, locate=locate, shutdown=shutdown, launch=launch)
        locate.assert_not_called()
        shutdown.assert_not_called()
        launch.assert_called_once()

    def test_refused_or_delayed_shutdown_never_relaunches(self):
        for refused in (True, False):
            with self.subTest(refused=refused):
                launch = Mock()
                shutdown = Mock(side_effect=RuntimeError('refused')) if refused else Mock()
                with patch.object(finish_driver.time, 'monotonic', side_effect=[0, 11]):
                    with self.assertRaises(RuntimeError):
                        finish_driver.finish(self.root, True, True, locate=lambda: 'desktop.exe',
                            processes=lambda exe: [object()], shutdown=shutdown, launch=launch)
                launch.assert_not_called()

    def test_other_profile_and_failed_registration_do_not_restart_active_app(self):
        launch, locate = Mock(), Mock()
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home/'different')}):
            with self.assertRaisesRegex(RuntimeError, 'different Codex profile'):
                finish_driver.finish(self.root, True, True, locate=locate, launch=launch)
        state = json.loads((self.root/'install-state.json').read_text())
        state['registered'] = False
        (self.root/'install-state.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(RuntimeError, 'not registered'):
            finish_driver.finish(self.root, True, True, locate=locate, launch=launch)
        launch.assert_not_called()
        locate.assert_not_called()

    def test_matching_custom_environment_does_not_prove_the_desktop_profile(self):
        state = json.loads((self.root/'install-state.json').read_text())
        state['home'] = str(self.home/'alternate')
        (self.root/'install-state.json').write_text(json.dumps(state))
        locate, launch = Mock(), Mock()
        with patch.dict(os.environ, {'CODEX_HOME': state['home']}):
            with self.assertRaisesRegex(RuntimeError, 'different Codex profile'):
                finish_driver.finish(self.root, True, True, locate=locate, launch=launch)
        locate.assert_not_called()
        launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
