#!/bin/sh
# Capitalism 2 모드 매니저 런처 (Linux / SteamOS). 인수 없이 실행하면 GUI(tkinter 없으면 도움말).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 cap2mod.py "$@"
else
  exec python cap2mod.py "$@"
fi
