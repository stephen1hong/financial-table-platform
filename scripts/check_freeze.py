"""Check the unchanged 12A source/reference bytes without re-freezing the holdout."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
frozen = json.loads((root/'evaluation/freeze.json').read_text())['fingerprint']
changed = [name for name, digest in frozen.items()
           if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest]
if changed:
    raise SystemExit('12A freeze mismatch: '+', '.join(changed))
print(f'12A freeze verified: {len(frozen)} source/reference files')
