"""Prepare the persistent release key supplied through GitHub Secrets."""
import base64
import os
from pathlib import Path

encoded = os.environ.get('ANDROID_KEYSTORE_BASE64', '')
required = ('ANDROID_KEYSTORE_BASE64', 'ANDROID_KEYSTORE_PASSWORD', 'ANDROID_KEY_ALIAS', 'ANDROID_KEY_PASSWORD')
configured = [name for name in required if os.environ.get(name)]
if configured and len(configured) != len(required):
    raise SystemExit('Incomplete Android release signing configuration: ' + ', '.join(name for name in required if name not in configured))
with open(os.environ['GITHUB_ENV'], 'a') as env:
    if encoded:
        path = Path(os.environ['RUNNER_TEMP']) / 'strmaction-release.keystore'
        path.write_bytes(base64.b64decode(encoded, validate=True))
        path.chmod(0o600)
        env.write(f'STRMACTION_KEYSTORE_PATH={path}\nANDROID_SIGNING_STATUS=release-key\n')
    else:
        env.write('ANDROID_SIGNING_STATUS=test-debug-and-unsigned-release\n')
