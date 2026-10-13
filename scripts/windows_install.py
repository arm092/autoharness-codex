"""Registration driver for the per-user Windows installer. Never deletes knowledge."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MARKETPLACE = 'autoharness-codex-windows'
PLUGIN = f'autoharness-codex@{MARKETPLACE}'
REQUIRED = ('--ignore-user-config', '--ignore-rules', '--ephemeral', '--output-schema', '--json')


def discover_codex():
    candidates = [os.environ.get('AUTOHARNESS_CODEX_BIN'), shutil.which('codex.exe'),
        str(Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'.sandbox-bin/codex.exe'),
        str(Path.home()/'.codex/.sandbox-bin/codex.exe')]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), '')


def canonical(path):
    text = str(path)
    if text.startswith('\\\\?\\'):
        text = text[4:]
    return os.path.normcase(os.path.realpath(text))


def run_codex(binary, home, args):
    env = os.environ | {'CODEX_HOME': str(home)}
    process = subprocess.run([str(binary), *args], env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    if process.returncode:
        raise RuntimeError(f'Codex {" ".join(args[:3])} failed ({process.returncode}): '
            + (process.stderr or process.stdout)[-2000:])
    return process.stdout


def validate_cli(binary, home, run=run_codex):
    if not Path(binary).is_file() or Path(binary).suffix.lower() != '.exe':
        raise ValueError('Select an existing Codex .exe executable.')
    version = run(binary, home, ['--version']).strip()
    if not version.lower().startswith(('codex ', 'codex-cli ')):
        raise ValueError('The selected executable is not Codex CLI.')
    help_text = run(binary, home, ['exec', '--help'])
    if not all(flag in help_text for flag in REQUIRED):
        raise ValueError('This Codex CLI is incompatible; update Codex first.')
    for args in (['plugin', 'add', '--help'], ['plugin', 'remove', '--help'],
                 ['plugin', 'marketplace', 'list', '--help']):
        run(binary, home, args)
    return version


def marketplaces(binary, home, run):
    value = json.loads(run(binary, home, ['plugin', 'marketplace', 'list', '--json']))
    return value.get('marketplaces', [])


def owned_marketplace(binary, home, plugin, run):
    matches = [m for m in marketplaces(binary, home, run) if m.get('name') == MARKETPLACE]
    if len(matches) > 1 or (matches and canonical(matches[0]['root']) != canonical(plugin)):
        raise ValueError('This marketplace name belongs to a different folder. Installation stopped without changing it.')
    return bool(matches)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.new')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True)+'\n', encoding='utf-8')
    temporary.replace(path)


def preflight(root, binary, home, run=run_codex):
    root, home = Path(root).resolve(), Path(home).resolve()
    validate_cli(binary, home, run)
    if root == home or root in home.parents or home in root.parents:
        raise ValueError('Install the program outside the Codex profile folder.')
    state_path = root/'install-state.json'
    if state_path.exists():
        old = json.loads(state_path.read_text(encoding='utf-8'))
        if canonical(old['home']) != canonical(home) or canonical(old['plugin']) != canonical(root/'plugin'):
            raise ValueError('Repair/update must use the original folder and Codex profile. Uninstall first to move it.')
    owned_marketplace(binary, home, root/'plugin', run)


def register(root, binary, home, run=run_codex):
    root, home, binary = Path(root).resolve(), Path(home).resolve(), Path(binary).resolve()
    plugin, state_path = root/'plugin', root/'install-state.json'
    if not (plugin/'.codex-plugin/plugin.json').is_file() or not (plugin/'runtime/python.exe').is_file():
        raise ValueError('The complete Windows plugin payload is missing.')
    preflight(root, binary, home, run)
    manifest = json.loads((plugin/'.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    state = dict(plugin=str(plugin), codex=str(binary), home=str(home), version=manifest['version'], registered=False)
    # A durable pending state makes a partially failed registration removable.
    atomic_json(state_path, state)
    atomic_json(plugin/'installation.json', {'codex': str(binary)})
    config_path = plugin/'.mcp.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    config['mcpServers']['library']['command'] = str(plugin/'runtime/python.exe')
    atomic_json(config_path, config)
    run(binary, home, ['plugin', 'marketplace', 'add', str(plugin), '--json'])
    run(binary, home, ['plugin', 'add', PLUGIN, '--json'])
    installed = json.loads(run(binary, home, ['plugin', 'list', '--json'])).get('installed', [])
    match = next((p for p in installed if p.get('pluginId') == PLUGIN and p.get('installed')), None)
    if not match or match.get('version') != manifest['version']:
        raise RuntimeError('Codex did not register the requested plugin version.')
    state['registered'] = True
    atomic_json(state_path, state)
    return state


def uninstall_state(root, run=run_codex):
    root = Path(root).resolve()
    state_path = root/'install-state.json'
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text(encoding='utf-8'))
    plugin = root/'plugin'
    if canonical(state['plugin']) != canonical(plugin):
        raise ValueError('Installation ownership mismatch; no Codex settings were changed.')
    binary, home = Path(state['codex']), Path(state['home'])
    owned_marketplace(binary, home, plugin, run)
    return state


def unregister(root, run=run_codex):
    root = Path(root).resolve()
    state = uninstall_state(root, run)
    if state is None:
        return {'status': 'not_registered'}
    binary, home = Path(state['codex']), Path(state['home'])
    installed = json.loads(run(binary, home, ['plugin', 'list', '--json'])).get('installed', [])
    if any(p.get('pluginId') == PLUGIN and p.get('installed') for p in installed):
        run(binary, home, ['plugin', 'remove', PLUGIN])
    if owned_marketplace(binary, home, root/'plugin', run):
        run(binary, home, ['plugin', 'marketplace', 'remove', MARKETPLACE, '--json'])
    # Only installation metadata is removed. The knowledge directory is never touched.
    (root/'install-state.json').unlink()
    return {'status': 'removed', 'knowledge_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'register', 'check-uninstall', 'unregister'])
    parser.add_argument('--root')
    parser.add_argument('--codex')
    parser.add_argument('--codex-home')
    parser.add_argument('--result')
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[2]
    try:
        binary = args.codex or discover_codex()
        home = args.codex_home or os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))
        if args.action == 'probe':
            preflight(root, binary, home)
            result = {'ok': True, 'codex': binary, 'home': home}
        elif args.action == 'register':
            result = {'ok': True, **register(root, binary, home)}
        elif args.action == 'check-uninstall':
            uninstall_state(root)
            result = {'ok': True, 'status': 'ready_to_uninstall'}
        else:
            result = {'ok': True, **unregister(root)}
        code = 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result, code = {'ok': False, 'error': str(error)}, 1
    if args.result:
        atomic_json(args.result, result)
    if sys.stdout is not None:
        print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
