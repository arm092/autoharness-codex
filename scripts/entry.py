"""Plugin entry point; no pip install is needed."""
import sys
import json
import os
from pathlib import Path

if sys.version_info < (3, 11):
    print('AutoHarness for Codex requires Python 3.11+.', file=sys.stderr)
    raise SystemExit(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
# The Windows installer records its selected CLI locally, without changing PATH
# or the user's environment. Explicit environment overrides still win.
installation = Path(__file__).resolve().parents[1] / 'installation.json'
if installation.is_file():
    try:
        binary = json.loads(installation.read_text(encoding='utf-8')).get('codex')
        if isinstance(binary, str) and Path(binary).is_file():
            os.environ.setdefault('AUTOHARNESS_CODEX_BIN', binary)
    except (OSError, ValueError):
        pass
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from autoharness_codex.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
