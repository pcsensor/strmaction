#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  uv venv .venv
fi
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python scripts/make_icons.py
.venv/bin/pyinstaller packaging/strmaction-desktop.spec --noconfirm --clean

echo
echo "构建完成：desktop/dist/StrmAction.app"
echo "签名/公证示例："
echo "  codesign --deep --force --options runtime --sign \"Developer ID Application: ...\" dist/StrmAction.app"
echo "  xcrun notarytool submit ... --wait"