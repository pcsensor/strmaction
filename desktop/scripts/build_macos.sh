#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  uv venv .venv
fi
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python scripts/make_icons.py
if [ "$(uname -m)" = "arm64" ]; then
  MPV_KEY="macos-arm64"
else
  MPV_KEY="macos-x64"
fi
if [ ! -f "vendor/mpv/$MPV_KEY/mpv" ] && [ ! -f "vendor/mpv/$MPV_KEY/mpv.app/Contents/MacOS/mpv" ]; then
  echo "提示：未发现 vendor/mpv/$MPV_KEY/mpv；构建产物将依赖用户已安装的 mpv。"
  echo "如需自带 mpv，请先运行："
  echo "  .venv/bin/python scripts/prepare_mpv.py --source /Applications/mpv.app"
fi
.venv/bin/pyinstaller packaging/strmaction-desktop.spec --noconfirm --clean

echo
echo "构建完成：desktop/dist/StrmAction.app"
echo "签名/公证示例："
echo "  codesign --deep --force --options runtime --sign \"Developer ID Application: ...\" dist/StrmAction.app"
echo "  xcrun notarytool submit ... --wait"
