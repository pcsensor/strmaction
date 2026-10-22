#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v flutter >/dev/null 2>&1 || {
  echo "未找到 flutter，请先安装 Flutter SDK 并加入 PATH。" >&2
  exit 1
}

flutter pub get
flutter analyze
flutter test
flutter build macos --release

APP="build/macos/Build/Products/Release/StrmAction.app"
if [ ! -d "$APP" ]; then
  APP="$(find build/macos/Build/Products/Release -maxdepth 1 -name '*.app' -print -quit)"
fi
if [ -z "${APP:-}" ] || [ ! -d "$APP" ]; then
  echo "未找到构建产物 .app" >&2
  exit 1
fi

mkdir -p dist
rm -f "dist/StrmAction-macOS.zip"
ditto -c -k --keepParent "$APP" "dist/StrmAction-macOS.zip"
echo "已生成：dist/StrmAction-macOS.zip"

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  echo "签名：$CODESIGN_IDENTITY"
  # --deep is convenient for development builds. For distribution, sign
  # nested dylibs/frameworks first and the outer app last.
  codesign --force --deep --options runtime --timestamp \
    --sign "$CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
fi

if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "公证：$NOTARY_PROFILE"
  xcrun notarytool submit "dist/StrmAction-macOS.zip" \
    --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
fi

if command -v create-dmg >/dev/null 2>&1; then
  rm -f "dist/StrmAction-macOS.dmg"
  create-dmg \
    --volname "StrmAction" \
    --window-pos 200 120 \
    --window-size 700 420 \
    --icon-size 100 \
    --app-drop-link 500 200 \
    "dist/StrmAction-macOS.dmg" \
    "$APP" || true
fi

echo ""
echo "构建完成：$APP"
echo "签名示例："
echo "  CODESIGN_IDENTITY='Developer ID Application: ...' ./scripts/build_macos.sh"
echo "公证示例："
echo "  NOTARY_PROFILE='strmaction-notary' ./scripts/build_macos.sh"
