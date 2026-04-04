#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="SmartVideoSplitter"
APP_BUNDLE="$SCRIPT_DIR/dist/${APP_NAME}.app"
DMG_PATH="$SCRIPT_DIR/dist/${APP_NAME}.dmg"
STAGING_DIR="$SCRIPT_DIR/release/dmg"

cd "$SCRIPT_DIR"

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "未检测到 hdiutil。该脚本仅支持在 macOS 上运行。"
  exit 1
fi

./build_macos_app.sh

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

cp -R "$APP_BUNDLE" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create \
  -volname "Smart Video Splitter" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo
echo "DMG 打包完成：$DMG_PATH"
