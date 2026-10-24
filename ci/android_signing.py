"""Prepare the existing release key only when GitHub Secrets supply it."""
import base64
import os
from pathlib import Path

encoded = os.environ.get('ANDROID_KEYSTORE_BASE64', '')
with open(os.environ['GITHUB_ENV'], 'a') as env:
    if encoded:
        path = Path(os.environ['RUNNER_TEMP']) / 'strmaction-release.keystore'
        path.write_bytes(base64.b64decode(encoded, validate=True))
        path.chmod(0o600)
        env.write(f'STRMACTION_KEYSTORE_PATH={path}\nANDROID_SIGNING_STATUS=existing-release-key\n')
    else:
        env.write('ANDROID_SIGNING_STATUS=test-debug-and-unsigned-release\n')
