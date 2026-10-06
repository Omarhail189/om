#!/usr/bin/env bash
set -euo pipefail
OM_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$OM_PROJECT_DIR/.venv/bin/python" ]]; then
    printf 'نفّذ أولًا: bash "%s/setup.sh"\n' "$OM_PROJECT_DIR" >&2
    exit 1
fi
exec "$OM_PROJECT_DIR/.venv/bin/python" "$OM_PROJECT_DIR/main.py" "$@"
