"""Enable the stable Windows plugin's missing certificate challenge callback.

The upstream 0.6.0 source contains a commented-out WebView2 handler. Keep the
small integration patch checked in and fail if its source anchor changes.
"""
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
config = ROOT / 'client_flutter/.dart_tool/package_config.json'
packages = json.loads(config.read_text())['packages']
package = next(p for p in packages if p['name'] == 'flutter_inappwebview_windows')
uri = urllib.parse.urljoin(config.as_uri(), package['rootUri'])
folder = Path(urllib.request.url2pathname(urllib.parse.urlparse(uri).path))
target = folder / 'windows/in_app_webview/in_app_webview.cpp'
source = target.read_text()
marker = '// StrmAction: strict private-CA verification'
if marker in source:
    start = source.index('    ' + marker)
    end = source.index('    if (userContentController)', start)
else:
    start = source.index('    /*\n    wil::com_ptr<ICoreWebView2_14> webView14;')
    end = source.index('    }*/', start) + len('    }*/')
patch = (ROOT / 'client_flutter/patches/windows_server_trust.cpp').read_text()
source = source[:start] + patch.rstrip() + '\n\n' + source[end:].lstrip('\n')
if '#include <urlmon.h>' not in source:
    source = '#include <algorithm>\n#include <cctype>\n#include <urlmon.h>\n#pragma comment(lib, "urlmon.lib")\n' + source
target.write_text(source)
print('Windows WebView private-CA callback enabled; default is deny.')
