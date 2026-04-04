#!/bin/zsh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/smart_video_splitter.py"

cd "$SCRIPT_DIR" || exit 1
/usr/bin/env python3 "$SCRIPT_PATH"
STATUS=$?

if [[ $STATUS -ne 0 ]]; then
  echo
  echo "程序异常退出，按回车关闭窗口..."
  read -r
fi

exit $STATUS
