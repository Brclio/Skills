#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo 'This runner is for macOS. On Windows, use scripts/run.ps1.' >&2
  exit 2
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd -P)
runtime_python="$HOME/Library/Application Support/zhixing-wxvideo-rd/runtime/bin/python"

if [ ! -x "$runtime_python" ]; then
  runtime_python=''
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      runtime_python=$(command -v "$candidate")
      break
    fi
  done
  if [ -z "$runtime_python" ]; then
    echo 'Python 3.10+ was not found. Install it, then run scripts/setup.sh.' >&2
    exit 2
  fi
fi

PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 "$runtime_python" "$script_dir/wx_video.py" "$@"
