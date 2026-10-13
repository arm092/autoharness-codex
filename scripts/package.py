"""Prepare a clean plugin ZIP with the current Python interpreter pinned."""
import argparse
import json
import os
import shlex
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('.codex-plugin', '.agents/plugins', 'hooks', 'skills', 'src', 'scripts')
FILES = ('.mcp.json', 'README.md', 'LICENSE', 'CHANGELOG.md', 'SECURITY.md')


def package(output, *, portable=False):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a fresh path.')
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = [ROOT/name for name in FILES if (ROOT/name).is_file()]
    paths += [p for folder in DIRECTORIES for p in (ROOT/folder).rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')]
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            rel, data = path.relative_to(ROOT).as_posix(), path.read_bytes()
            if not portable and rel == '.mcp.json':
                config = json.loads(data)
                config['mcpServers']['library']['command'] = sys.executable
                data = (json.dumps(config, indent=2)+'\n').encode()
            if not portable and rel == 'hooks/hooks.json':
                config = json.loads(data)
                interpreter = shlex.quote(sys.executable)
                for groups in config['hooks'].values():
                    for group in groups:
                        for handler in group['hooks']:
                            if os.name == 'nt':
                                executable = sys.executable.replace("'", "''")
                                handler['commandWindows'] = 'powershell.exe -NoProfile -NonInteractive -Command "& \''+executable+'\' \'${PLUGIN_ROOT}/scripts/entry.py\' hook"'
                            else:
                                handler['command'] = interpreter+' "${PLUGIN_ROOT}/scripts/entry.py" hook'
                data = (json.dumps(config, indent=2)+'\n').encode()
            archive.writestr(rel, data)
    return str(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--portable', action='store_true')
    args = parser.parse_args()
    print(package(args.output, portable=args.portable))
