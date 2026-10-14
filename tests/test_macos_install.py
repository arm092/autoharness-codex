import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('macos_install', ROOT/'scripts/macos_install.py')
mac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac)


class MacInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.home, self.payload = base/"program space's", base/'profile', base/'payload'
        self.binary = base/'codex'
        self.binary.touch()
        self.binary.chmod(0o755)
        self.source = self.payload/'plugin'
        (self.source/'.codex-plugin').mkdir(parents=True)
        (self.source/'.codex-plugin/plugin.json').write_text(json.dumps({'version': '1.3.0'}))
        (self.source/'runtime/bin').mkdir(parents=True)
        (self.source/'runtime/bin/python3').touch()
        (self.source/'.mcp.json').write_text(json.dumps({'mcpServers': {'library': {'command': 'python'}}}))
        self.markets = [{'name': 'other', 'root': '/other'}]
        self.installed, self.calls = [], []
        self.fail = False
        self.knowledge = self.home/'autoharness-codex/knowledge.txt'
        self.knowledge.parent.mkdir(parents=True)
        self.knowledge.write_text('keep this')

    def run_codex(self, binary, home, args):
        self.calls.append(args)
        if args == ['--version']: return 'codex-cli 0.162.1'
        if args == ['exec', '--help']: return ' '.join(mac.REQUIRED)
        if args[:3] == ['plugin', 'marketplace', 'list']: return json.dumps({'marketplaces': self.markets})
        if args[:2] == ['plugin', 'list']: return json.dumps({'installed': self.installed})
        if args[:3] == ['plugin', 'marketplace', 'add']:
            if not any(m['name'] == mac.MARKETPLACE for m in self.markets):
                self.markets.append({'name': mac.MARKETPLACE, 'root': str(self.root)})
        elif args[:2] == ['plugin', 'add']:
            if self.fail: raise RuntimeError('refused')
            state = mac.read_state(self.root)
            self.installed = [{'pluginId': mac.PLUGIN, 'installed': True, 'version': '1.3.0', 'source': {'path': state['plugin']}}]
        elif args[:2] == ['plugin', 'remove']: self.installed = []
        elif args[:3] == ['plugin', 'marketplace', 'remove']:
            self.markets = [m for m in self.markets if m['name'] != mac.MARKETPLACE]
        return '{}'

    def install(self):
        return mac.install(self.payload, self.root, self.binary, self.home, self.run_codex)

    def test_update_keeps_previous_release_and_uninstall_preserves_knowledge(self):
        first = self.install()
        second = self.install()
        self.assertNotEqual(first['plugin'], second['plugin'])
        self.assertTrue(Path(first['plugin']).is_dir())
        self.assertEqual(second['previous_plugin'], first['plugin'])
        config = json.loads((Path(second['plugin'])/'.mcp.json').read_text())
        self.assertTrue(Path(config['mcpServers']['library']['command']).samefile(Path(second['plugin'])/'runtime/bin/python3'))
        self.assertTrue(mac.unregister(self.root, self.run_codex)['knowledge_preserved'])
        self.assertEqual(self.markets, [{'name': 'other', 'root': '/other'}])
        self.assertEqual(self.knowledge.read_text(), 'keep this')
        self.assertTrue(Path(first['plugin']).exists())

    def test_foreign_folder_and_marketplace_are_never_overwritten(self):
        self.root.mkdir()
        sentinel = self.root/'unrelated.txt'
        sentinel.write_text('private')
        with self.assertRaises(ValueError): self.install()
        self.assertEqual(sentinel.read_text(), 'private')
        sentinel.unlink()
        self.markets.append({'name': mac.MARKETPLACE, 'root': '/foreign'})
        self.calls.clear()
        with self.assertRaises(ValueError): self.install()
        self.assertFalse(any('add' in args for args in self.calls))

    def test_failed_registration_retains_pending_release_for_repair(self):
        self.fail = True
        with self.assertRaises(RuntimeError): self.install()
        state = mac.read_state(self.root)
        self.assertFalse(state['registered'])
        self.assertTrue(Path(state['plugin']).is_dir())
        self.fail = False
        self.assertTrue(self.install()['registered'])
        self.assertEqual(self.knowledge.read_text(), 'keep this')

    def test_profile_change_and_metadata_escape_do_not_modify_registration(self):
        self.install()
        self.calls.clear()
        with self.assertRaises(ValueError):
            mac.install(self.payload, self.root, self.binary, self.home/'other', self.run_codex)
        state_path = self.root/'install-state.json'
        state = json.loads(state_path.read_text())
        state['plugin'] = str(self.home)
        state_path.write_text(json.dumps(state))
        with self.assertRaises(ValueError): mac.unregister(self.root, self.run_codex)
        self.assertFalse(any('remove' in args or 'add' in args for args in self.calls))

    def test_failed_copy_preserves_usable_previous_install_state(self):
        previous = self.install()
        state_bytes = (self.root/'install-state.json').read_bytes()
        self.calls.clear()
        with patch.object(mac.shutil, 'copytree', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.install()
        self.assertEqual((self.root/'install-state.json').read_bytes(), state_bytes)
        self.assertTrue((Path(previous['plugin'])/'runtime/bin/python3').is_file())
        self.assertFalse(any('add' in args for args in self.calls))
        self.assertTrue(mac.unregister(self.root, self.run_codex)['knowledge_preserved'])

    def test_failed_fresh_state_publication_is_retryable_without_foreign_folder(self):
        write = mac.atomic_json
        def fail_state(path, value):
            if Path(path).name == 'install-state.json':
                raise OSError('disk full while publishing ownership')
            return write(path, value)
        with patch.object(mac, 'atomic_json', side_effect=fail_state):
            with self.assertRaises(OSError): self.install()
        self.assertFalse(self.root.exists())
        self.assertFalse(any('add' in args for args in self.calls))
        self.assertTrue(self.install()['registered'])
        self.assertEqual(self.knowledge.read_text(), 'keep this')


if __name__ == '__main__': unittest.main()
