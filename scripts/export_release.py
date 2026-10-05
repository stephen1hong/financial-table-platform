"""Export the proposed working tree without staging, committing, or copying caches."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.gitattributes', 'pyproject.toml', 'README.md',
              'SUPPORTED_FORMATS.md', 'CHANGELOG.md', 'LICENSE_DECISION.md',
              'THIRD_PARTY_NOTICES.md', 'MANIFEST.in'}
PREFIXES = ('src/sec_downloader/', 'tests/', 'scripts/', 'evaluation/',
            'demo/', 'requirements/', 'docs/', '.github/')


def proposed_files():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard'], cwd=ROOT).decode().split('\0')
    selected = []
    for name in sorted(set(names) - {''}):
        path = ROOT/name
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        if name in ROOT_FILES or name == 'data/manifest.json' or name.startswith(PREFIXES):
            if path.suffix.lower() in {'.pyc','.db','.sqlite','.sqlite3','.onnx','.pem','.key'}:
                raise ValueError(f'Unexpected private/generated file: {name}')
            if path.stat().st_size > 2_000_000:
                raise ValueError(f'Unexpected large release file: {name}')
            selected.append(name)
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    target = args.output.resolve()
    if target.exists():
        raise SystemExit('Output must not exist; refusing to overwrite')
    files = proposed_files()
    target.mkdir(parents=True)
    records = []
    for name in files:
        destination = target/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, destination)
        records.append({'path':name, 'bytes':destination.stat().st_size,
                        'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    manifest = target.parent/(target.name+'-files.json')
    manifest.write_text(json.dumps(records, indent=2)+'\n')
    print(f'Exported {len(records)} files; exact inventory: {manifest}')


if __name__ == '__main__':
    main()
