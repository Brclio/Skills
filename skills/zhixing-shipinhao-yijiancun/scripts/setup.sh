#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo 'This setup script is for macOS. On Windows, use scripts/setup.ps1.' >&2
  exit 2
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd -P)
skill_dir=$(dirname "$script_dir")
runtime_dir="$HOME/Library/Application Support/zhixing-wxvideo-rd/runtime"
runtime_python="$runtime_dir/bin/python"

find_python() {
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$runtime_python" ]; then
  system_python=$(find_python) || {
    echo 'Python 3.10+ was not found. Install it, then run setup again.' >&2
    exit 2
  }
  mkdir -p "$(dirname "$runtime_dir")"
  "$system_python" -m venv "$runtime_dir"
fi

"$runtime_python" -m pip install --disable-pip-version-check -r "$skill_dir/requirements.txt"
echo 'Dependencies installed in an isolated local environment; no browser, root certificate or system proxy was changed.'
PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 "$runtime_python" "$script_dir/wx_video.py" doctor
