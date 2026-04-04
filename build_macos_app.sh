#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_FILE="smart_video_splitter.py"
APP_NAME="SmartVideoSplitter"
SPEC_FILE="${APP_NAME}.spec"

cd "$SCRIPT_DIR"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "未检测到 pyinstaller。请先执行：python3 -m pip install pyinstaller"
  exit 1
fi

ADD_BINARY_ARGS=()
for BIN_NAME in ffmpeg ffprobe; do
  if BIN_PATH="$(command -v "$BIN_NAME" 2>/dev/null)"; then
    echo "将打包二进制: $BIN_PATH"
    ADD_BINARY_ARGS+=(--add-binary "$BIN_PATH:.")
  else
    echo "未找到 $BIN_NAME，将依赖目标机器系统 PATH。"
  fi
done

rm -rf build dist

pyinstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --specpath "$SCRIPT_DIR" \
  "${ADD_BINARY_ARGS[@]}" \
  "$PY_FILE"

echo
echo "打包完成：$SCRIPT_DIR/dist/$APP_NAME.app"
