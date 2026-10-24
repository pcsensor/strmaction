"""Record the exact source and checksums alongside downloadable client packages."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('platform', choices=('android', 'ios', 'windows', 'macos'))
parser.add_argument('directory', type=Path)
parser.add_argument('--signing', required=True)
args = parser.parse_args()
extensions = {'android': '.apk', 'ios': '.ipa', 'windows': '.zip', 'macos': '.zip'}
packages = sorted(args.directory.glob('*' + extensions[args.platform]))
if not packages:
    raise SystemExit('No package found for ' + args.platform)
metadata = {
    'platform': args.platform,
    'commit': os.environ.get('GITHUB_SHA', 'local'),
    'run_url': f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
    'runner': platform.platform(),
    'flutter_version': os.environ.get('FLUTTER_VERSION'),
    'signing': args.signing,
    'packages': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in packages],
}
(args.directory / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
