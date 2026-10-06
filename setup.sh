#!/usr/bin/env bash
set -euo pipefail
OM_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OM_PYTHON="${OM_PYTHON:-python3}"
"$OM_PYTHON" -c 'import sys; assert (3, 11) <= sys.version_info < (3, 14), "يلزم Python 3.11 أو 3.12 أو 3.13؛ حدد OM_PYTHON إذا كانت لديك عدة إصدارات."'
"$OM_PYTHON" -m venv "$OM_PROJECT_DIR/.venv"
"$OM_PROJECT_DIR/.venv/bin/python" -m pip install -r "$OM_PROJECT_DIR/requirements.txt"
"$OM_PROJECT_DIR/.venv/bin/python" -m pip check
printf 'اكتمل تجهيز المشروع. التشغيل: bash "%s/run.sh" --symbol GSPC\n' "$OM_PROJECT_DIR"
