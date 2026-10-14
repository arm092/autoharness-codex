"""Per-user macOS install/remove using a bundled runtime and immutable releases."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import uuid
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_install import run_codex, canonical, REQUIRED

OWNER = 'arm092.autoharness-codex.macos'
MARKETPLACE = 'autoharness-codex-macos'
PLUGIN = 'autoharness-codex@'+MARKETPLACE


def default_root():
    return Path.home()/'Library/Application Support/AutoHarness for Codex'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2)
        stream.write('\n')
    temporary.replace(path)


def managed(root, relative):
    path = Path(root)/relative
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Installation metadata escapes its owned folder.')
    return path


def discover_codex():
    candidates = [os.environ.get('AUTOHARNESS_CODEX_BIN'), shutil.which('codex'),
        str(Path.home()/'.codex/.sandbox-bin/codex')]
    for base in (Path('/Applications'), Path.home()/'Applications'):
        for app in ('Codex.app', 'ChatGPT.app'):
            candidates.append(str(base/app/'Contents/Resources/codex'))
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), '')


def validate(binary, home, run):
    if not binary or not Path(binary).is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Select the executable Codex CLI supplied with your desktop app or CLI installation.')
    version = run(binary, home, ['--version']).strip()
    if not version.startswith(('codex ', 'codex-cli ')):
        raise ValueError('Selected executable is not Codex CLI.')
    help_text = run(binary, home, ['exec', '--help'])
    if not all(option in help_text for option in REQUIRED):
        raise ValueError('Update Codex: its CLI does not support this plugin runtime.')


def owned_market(root, binary, home, run):
    markets = json.loads(run(binary, home, ['plugin', 'marketplace', 'list', '--json'])).get('marketplaces', [])
    matches = [m for m in markets if m.get('name') == MARKETPLACE]
    if len(matches) > 1 or (matches and canonical(matches[0]['root']) != canonical(root)):
        raise ValueError('The AutoHarness marketplace belongs to another folder; no changes were made.')
    return bool(matches)


def read_state(root, home=None):
    root = Path(root).resolve()
    path = managed(root, 'install-state.json')
    if not path.is_file():
        if root.exists() and any(root.iterdir()):
            raise ValueError('This nonempty folder is not an AutoHarness macOS installation.')
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('owner') != OWNER or canonical(state.get('root', '')) != canonical(root):
        raise ValueError('Installation ownership mismatch.')
    if home and canonical(state['home']) != canonical(home):
        raise ValueError('Update must use the original Codex profile.')
    if state.get('plugin') and not Path(state['plugin']).resolve().is_relative_to(root/'releases'):
        raise ValueError('Installation release escapes its owned folder.')
    return state


def preflight(root, binary, home, run):
    root, home = Path(root).resolve(), Path(home).resolve()
    data = Path(os.environ.get('AUTOHARNESS_CODEX_DATA', str(home/'autoharness-codex'))).resolve()
    if root == home or root in home.parents or home in root.parents or data == root or root in data.parents:
        raise ValueError('Keep the program folder separate from your Codex profile and knowledge storage.')
    state = read_state(root, home)
    validate(binary, home, run)
    owned_market(root, binary, home, run)
    managed(root, '.agents/plugins/marketplace.json')
    managed(root, 'releases')
    return state


def install(payload, root, binary, home, run=run_codex):
    payload, root, home = Path(payload).resolve(), Path(root).resolve(), Path(home).resolve()
    source = payload/'plugin'
    if not (source/'.codex-plugin/plugin.json').is_file() or not (source/'runtime/bin/python3').is_file():
        raise ValueError('Complete bundled macOS payload is missing.')
    old = preflight(root, binary, home, run)
    manifest = json.loads((source/'.codex-plugin/plugin.json').read_text())
    root.mkdir(parents=True, exist_ok=True)
    release = managed(root, 'releases')/(manifest['version']+'-'+uuid.uuid4().hex)
    plugin = release/'plugin'
    # Existing releases are never overwritten or deleted, including on failed registration.
    state = dict(owner=OWNER, root=str(root), home=str(home), codex=str(Path(binary).resolve()),
        plugin=str(plugin), version=manifest['version'], registered=False,
        previous_plugin=old.get('plugin') if old else None)
    atomic_json(managed(root, 'install-state.json'), state)
    shutil.copytree(source, plugin, symlinks=True)
    atomic_json(plugin/'installation.json', {'codex': state['codex']})
    config = json.loads((plugin/'.mcp.json').read_text())
    config['mcpServers']['library']['command'] = str(plugin/'runtime/bin/python3')
    atomic_json(plugin/'.mcp.json', config)
    market = dict(name=MARKETPLACE, interface={'displayName': 'AutoHarness for Codex'}, plugins=[dict(
        name='autoharness-codex', source=dict(source='local', path='./'+str(plugin.relative_to(root)).replace(os.sep, '/')))])
    atomic_json(managed(root, '.agents/plugins/marketplace.json'), market)
    run(binary, home, ['plugin', 'marketplace', 'add', str(root), '--json'])
    run(binary, home, ['plugin', 'add', PLUGIN, '--json'])
    installed = json.loads(run(binary, home, ['plugin', 'list', '--json'])).get('installed', [])
    if not any(p.get('pluginId') == PLUGIN and p.get('installed') and p.get('version') == manifest['version'] for p in installed):
        raise RuntimeError('Codex did not register the requested version. Program releases were retained for recovery.')
    state['registered'] = True
    atomic_json(managed(root, 'install-state.json'), state)
    return state


def unregister(root, run=run_codex):
    root = Path(root).resolve()
    state = read_state(root)
    if not state:
        return {'status': 'not_installed'}
    binary, home = state['codex'], Path(state['home'])
    data = Path(os.environ.get('AUTOHARNESS_CODEX_DATA', str(home/'autoharness-codex'))).resolve()
    if root == data or root in data.parents:
        raise ValueError('Knowledge storage is inside the program folder; removal stopped.')
    owned_market(root, binary, home, run)
    installed = json.loads(run(binary, home, ['plugin', 'list', '--json'])).get('installed', [])
    if any(p.get('pluginId') == PLUGIN and p.get('installed') for p in installed):
        run(binary, home, ['plugin', 'remove', PLUGIN])
    if owned_market(root, binary, home, run):
        run(binary, home, ['plugin', 'marketplace', 'remove', MARKETPLACE, '--json'])
    state['registered'] = False
    atomic_json(managed(root, 'install-state.json'), state)
    return {'status': 'removed', 'knowledge_preserved': True}


def dialog(text, buttons, default):
    script = 'on run argv\nset msg to item 1 of argv\nset labels to items 3 thru -1 of argv\nset answer to display dialog msg buttons labels default button (item 2 of argv) with title "AutoHarness for Codex"\nreturn button returned of answer\nend run'
    result = subprocess.run(['/usr/bin/osascript', '-e', script, text, default, *buttons],
        capture_output=True, text=True, timeout=600)
    if result.returncode:
        return 'Cancel'
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'unregister'])
    parser.add_argument('--payload')
    parser.add_argument('--root', default=str(default_root()))
    parser.add_argument('--codex')
    parser.add_argument('--codex-home')
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    try:
        if args.gui:
            choice = dialog('Install/update AutoHarness with bundled Python. Close Codex before updating.\n\nУстановка AutoHarness со встроенным Python. Перед обновлением закрой Codex.' if args.action == 'install'
                else 'Remove the plugin registration? Knowledge is preserved.\n\nУдалить плагин? Библиотека знаний сохранится.',
                ['Cancel', 'Install' if args.action == 'install' else 'Remove'], 'Install' if args.action == 'install' else 'Remove')
            if choice == 'Cancel':
                return 0
        if args.action == 'install':
            binary = args.codex or discover_codex()
            if not binary and args.gui:
                selected = subprocess.run(['/usr/bin/osascript', '-e', 'POSIX path of (choose file with prompt "Select Codex CLI executable")'], capture_output=True, text=True)
                if selected.returncode:
                    return 0
                binary = selected.stdout.strip()
            home = args.codex_home or os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))
            result = install(args.payload, args.root, binary, home)
            if args.gui and dialog('Installed. Review/trust five hooks via /hooks in Codex CLI.\n\nУстановлено. Разреши пять хуков через /hooks в Codex CLI.', ['Done', 'Open Codex'], 'Open Codex') == 'Open Codex':
                url = 'codex://plugins/autoharness-codex?marketplacePath='+quote(str(Path(args.root).resolve()/'.agents/plugins/marketplace.json'), safe='')
                subprocess.run(['/usr/bin/open', url], check=True)
        else:
            result = unregister(args.root)
            if args.gui:
                dialog('Plugin removed. Knowledge and program releases were retained. You may move the AutoHarness program folder to Trash.\n\nПлагин удалён. Знания сохранены. Папку программы AutoHarness можно переместить в Корзину.', ['Done'], 'Done')
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        if args.gui:
            dialog(str(error), ['Done'], 'Done')
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
