"""Verify the release APK uses the repository's public release certificate."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import ssl
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('apk', type=Path)
args = parser.parse_args()
certificate = Path(__file__).with_name('android-release-certificate.pem')
expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
apksigner = Path(os.environ['ANDROID_HOME']) / 'build-tools/34.0.0/apksigner'
result = subprocess.run([str(apksigner), 'verify', '--verbose', '--print-certs', str(args.apk)],
                        check=True, capture_output=True, text=True)
actual = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)$', result.stdout, re.M)
if [value.lower() for value in actual] != [expected]:
    raise SystemExit('Release APK signing certificate does not match ci/android-release-certificate.pem')
print('Release APK signature verified; certificate SHA-256: ' + expected)
