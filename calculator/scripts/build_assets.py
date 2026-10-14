"""Copy the single scoring engine to web and WeChat clients, or verify parity."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
content = (ROOT / 'shared' / 'scoring.js').read_bytes()
for target in [ROOT / 'web' / 'scoring.js', ROOT / 'wechat' / 'utils' / 'scoring.js']:
    if args.check:
        if not target.exists() or target.read_bytes() != content:
            raise SystemExit(f'Scoring copy is stale: {target.relative_to(ROOT)}')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
print('OK: shared, web and WeChat engines are identical.')
