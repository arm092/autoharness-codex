"""Build native per-user macOS installer apps and DMG, with a pinned runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

from package import package, ROOT

RUNTIMES = {
    'arm64': ('aarch64', '16a5332fb0dcb77f163fc8f8cbccd95be1644cc53e68e5d2a79f50afd6680a0e'),
    'x86_64': ('x86_64', 'f507ae04eb7747cd97cb484e8c5d83936cbfc52d9b08a1f35c00b47c707b1ae1'),
}
PYTHON_VERSION, RUNTIME_RELEASE = '3.13.16', '20261013'


def runtime_source(arch):
    target, digest = RUNTIMES[arch]
    filename = f'cpython-{PYTHON_VERSION}%2B{RUNTIME_RELEASE}-{target}-apple-darwin-install_only_stripped.tar.gz'
    return 'https://github.com/astral-sh/python-build-standalone/releases/download/'+RUNTIME_RELEASE+'/'+filename, digest


def app_bundle(folder, name, version, launcher):
    app = folder/(name+'.app')
    executable = app/'Contents/MacOS/launcher'
    executable.parent.mkdir(parents=True)
    (app/'Contents/Resources').mkdir()
    (app/'Contents/Resources/launcher.sh').write_text(launcher, encoding='utf-8', newline='\n')
    native = r'''#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
  char path[PATH_MAX], resolved[PATH_MAX], script[PATH_MAX]; uint32_t length=sizeof(path);
  if (_NSGetExecutablePath(path,&length) || !realpath(path,resolved)) return 1;
  char *slash=strrchr(resolved,'/'); if (!slash) return 1; *slash=0;
  if (snprintf(script,sizeof(script),"%s/../Resources/launcher.sh",resolved)>=(int)sizeof(script)) return 1;
  execl("/bin/sh","/bin/sh",script,(char*)0); perror("AutoHarness launcher"); return 1;
}'''
    subprocess.run(['/usr/bin/clang', '-x', 'c', '-', '-o', str(executable)], input=native, text=True, check=True)
    with (app/'Contents/Info.plist').open('wb') as stream:
        plistlib.dump(dict(CFBundleName=name, CFBundleDisplayName=name, CFBundleExecutable='launcher',
            CFBundleIdentifier='am.apricode.autoharness.'+('installer' if name.startswith('Install') else 'uninstaller'),
            CFBundlePackageType='APPL', CFBundleShortVersionString=version, CFBundleVersion=version,
            LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True), stream)
    return app


def build(work_dir, output_dir, arch=None):
    if platform.system() != 'Darwin':
        raise RuntimeError('Build this package on a macOS runner; cross-built packages are not claimed tested.')
    arch = arch or platform.machine()
    if arch not in RUNTIMES or arch != platform.machine():
        raise ValueError('Use a native arm64 or x86_64 macOS runner.')
    work, output = Path(work_dir).resolve(), Path(output_dir).resolve()
    if work.exists():
        raise ValueError('Choose a fresh work directory.')
    work.mkdir(parents=True)
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT/'.codex-plugin/plugin.json').read_text())['version']
    stem = f'AutoHarness-{version}-macOS-{arch}'
    artifacts = [output/(stem+suffix) for suffix in ('.dmg', '.zip', '-SHA256.txt')]
    if any(path.exists() for path in artifacts):
        raise ValueError('Output already exists.')
    distribution = work/'distribution'
    distribution.mkdir()
    launcher = '#!/bin/sh\nset -eu\napp_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"\npayload="$app_root/Resources/payload"\nexec "$payload/plugin/runtime/bin/python3" -I "$payload/plugin/scripts/macos_install.py" install --payload "$payload" --gui\n'
    app = app_bundle(distribution, 'Install AutoHarness', version, launcher)
    payload = app/'Contents/Resources/payload'
    source = work/'source.zip'
    package(source, portable=True)
    with zipfile.ZipFile(source) as archive:
        archive.extractall(payload/'plugin')
    url, expected = runtime_source(arch)
    runtime_archive = work/'runtime.tar.gz'
    with urllib.request.urlopen(url, timeout=120) as response:
        runtime_archive.write_bytes(response.read())
    if hashlib.sha256(runtime_archive.read_bytes()).hexdigest() != expected:
        raise ValueError('Standalone Python SHA256 mismatch.')
    with tarfile.open(runtime_archive) as archive:
        archive.extractall(work/'runtime-extracted', filter='data')
    shutil.move(str(work/'runtime-extracted/python'), str(payload/'plugin/runtime'))
    # Install-only Python uses internal relative links; data-filter rejects escapes.
    runtime = payload/'plugin/runtime'
    for path in runtime.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(runtime.resolve()):
            raise ValueError('Runtime symlink escapes its package.')
    (payload/'runtime-source.json').write_text(json.dumps(dict(python=PYTHON_VERSION, architecture=arch,
        url=url, sha256=expected), indent=2)+'\n')
    hooks_path = payload/'plugin/hooks/hooks.json'
    hooks = json.loads(hooks_path.read_text())
    for groups in hooks['hooks'].values():
        for group in groups:
            for handler in group['hooks']:
                handler['command'] = '"${PLUGIN_ROOT}/runtime/bin/python3" -I "${PLUGIN_ROOT}/scripts/entry.py" hook'
                handler.pop('commandWindows', None)
    hooks_path.write_text(json.dumps(hooks, indent=2)+'\n')
    config = json.loads((payload/'plugin/.mcp.json').read_text())
    config['mcpServers']['library']['command'] = './runtime/bin/python3'
    config['mcpServers']['library']['args'].insert(0, '-I')
    (payload/'plugin/.mcp.json').write_text(json.dumps(config, indent=2)+'\n')
    uninstall_launcher = '#!/bin/sh\nset -eu\nroot="$HOME/Library/Application Support/AutoHarness for Codex"\nif [ ! -f "$root/install-state.json" ]; then /usr/bin/osascript -e \'display dialog "AutoHarness is not installed." buttons {"Done"}\'; exit 0; fi\npython_path=$( /usr/bin/plutil -extract plugin raw "$root/install-state.json" )\nexec "$python_path/runtime/bin/python3" -I "$python_path/scripts/macos_install.py" unregister --root "$root" --gui\n'
    app_bundle(distribution, 'Uninstall AutoHarness', version, uninstall_launcher)
    shutil.copy2(ROOT/'installer/INSTALL-macOS.txt', distribution/'READ ME.txt')
    # Ad-hoc signing protects local bundle integrity; it is not Developer ID/notarization.
    for bundle in distribution.glob('*.app'):
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    subprocess.run(['/usr/bin/hdiutil', 'create', '-volname', 'AutoHarness '+version,
        '-srcfolder', str(distribution), '-format', 'UDZO', str(artifacts[0])], check=True)
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(distribution), str(artifacts[1])], check=True)
    artifacts[2].write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in artifacts[:2]))
    return artifacts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--arch', choices=list(RUNTIMES))
    args = parser.parse_args()
    for path in build(args.work_dir, args.output_dir, args.arch):
        print(path)
