"""Plugin entry point; no pip install is needed."""
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print('AutoHarness for Codex requires Python 3.11+.', file=sys.stderr)
    raise SystemExit(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from autoharness_codex.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
