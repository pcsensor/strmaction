"""Record the exact source and checksums alongside downloadable client packages."""
import argparse
import hashlib
import json
import os
import platform
import re
import ssl
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
    'app_version': re.search(r'^version: ([^\n]+)', (Path(__file__).resolve().parents[1] / 'client_flutter/pubspec.yaml').read_text(), re.M).group(1),
    'signing': args.signing,
    'packages': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in packages],
}
if args.platform == 'android' and args.signing == 'release-key':
    certificate = Path(__file__).with_name('android-release-certificate.pem')
    metadata['signing_certificate_sha256'] = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
(args.directory / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
