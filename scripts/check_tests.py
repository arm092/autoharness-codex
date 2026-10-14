"""Run unittest discovery with explicit collection and non-skipped-test gates."""
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-dir', default=str(ROOT/'tests'))
    parser.add_argument('--minimum', type=int, default=1)
    args = parser.parse_args()
    if args.minimum < 1:
        parser.error('minimum must be positive')
    sys.path.insert(0, str(ROOT/'src'))
    suite = unittest.defaultTestLoader.discover(args.start_dir)
    count = suite.countTestCases()
    print(f'Collected {count} tests; required minimum {args.minimum}.', flush=True)
    if count < args.minimum:
        print('FAIL: insufficient test collection.', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = result.testsRun-len(result.skipped)
    print(f'Executed {executed}; skipped {len(result.skipped)}.', flush=True)
    return 0 if result.wasSuccessful() and executed >= args.minimum else 1


if __name__ == '__main__':
    raise SystemExit(main())
