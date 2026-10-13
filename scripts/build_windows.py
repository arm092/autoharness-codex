"""Build a Windows x64 package and Inno Setup installer with embedded Python.

Build-time Python and Inno Setup are required; installed users need neither.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from package import package, ROOT

PYTHON_VERSION = '3.13.16'
RUNTIME_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
RUNTIME_SHA256 = '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'


def extract_runtime(archive, destination):
    archive, destination = Path(archive), Path(destination)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise ValueError('Embedded Python SHA-256 mismatch.')
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            # The pinned official embed distribution consists of top-level files.
            if '/' in info.filename or '\\' in info.filename or info.filename in ('.', '..'):
                raise ValueError('Unexpected embedded runtime archive layout.')
        zipped.extractall(destination)


def build(work_dir, output_dir, compiler, runtime_archive=None):
    work, output = Path(work_dir).resolve(), Path(output_dir).resolve()
    if work.exists():
        raise ValueError('Choose a fresh work directory.')
    work.mkdir(parents=True)
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT/'.codex-plugin/plugin.json').read_text())['version']
    stem = f'AutoHarness-{version}-Windows-x64'
    if any((output/name).exists() for name in (stem+'.zip', stem+'-Setup.exe', stem+'-SHA256.txt')):
        raise ValueError('Output already exists; choose a fresh output directory.')
    runtime_archive = Path(runtime_archive) if runtime_archive else work/'python-embed.zip'
    if not runtime_archive.exists():
        with urllib.request.urlopen(RUNTIME_URL, timeout=120) as response:
            runtime_archive.write_bytes(response.read())
    payload = work/'payload'
    plugin = payload/'plugin'
    source = work/'source.zip'
    package(source, portable=True)
    with zipfile.ZipFile(source) as archive:
        archive.extractall(plugin)
    extract_runtime(runtime_archive, plugin/'runtime')
    marketplace = plugin/'.agents/plugins/marketplace.json'
    value = json.loads(marketplace.read_text())
    value['name'] = 'autoharness-codex-windows'
    marketplace.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    hooks = plugin/'hooks/hooks.json'
    value = json.loads(hooks.read_text())
    for groups in value['hooks'].values():
        for group in groups:
            for handler in group['hooks']:
                handler['commandWindows'] = ('powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass '
                    '-File "${PLUGIN_ROOT}/scripts/windows_hook.ps1"')
    hooks.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    # Installation pins this path to the user's chosen permanent folder before registration.
    mcp = json.loads((plugin/'.mcp.json').read_text())
    mcp['mcpServers']['library']['command'] = './runtime/python.exe'
    (plugin/'.mcp.json').write_text(json.dumps(mcp, indent=2)+'\n', encoding='utf-8')
    (payload/'AutoHarness.cmd').write_text('@echo off\n"%~dp0plugin\\runtime\\python.exe" "%~dp0plugin\\scripts\\entry.py" %*\n', encoding='utf-8')
    shutil.copy2(ROOT/'installer/INSTALL.txt', payload/'INSTALL.txt')
    (payload/'runtime-source.json').write_text(json.dumps(dict(version=PYTHON_VERSION, url=RUNTIME_URL,
        sha256=RUNTIME_SHA256), indent=2)+'\n', encoding='utf-8')
    zipped = output/(stem+'.zip')
    with zipfile.ZipFile(zipped, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(payload.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(payload))
    subprocess.run([str(Path(compiler).resolve()), f'/DPayloadDir={payload}', f'/DAppVersion={version}',
        f'/DOutputDir={output}', f'/DOutputName={stem}-Setup', str(ROOT/'installer/windows.iss')], check=True)
    artifacts = (zipped, output/(stem+'-Setup.exe'))
    (output/(stem+'-SHA256.txt')).write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts), encoding='utf-8')
    return artifacts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--runtime-archive')
    args = parser.parse_args()
    for artifact in build(args.work_dir, args.output_dir, args.compiler, args.runtime_archive):
        print(artifact)
