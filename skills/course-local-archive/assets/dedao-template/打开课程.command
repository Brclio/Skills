#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
exec python3 scripts/serve.py --open
