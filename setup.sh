#!/usr/bin/env bash
set -euo pipefail
OM_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

om_supported_python() {
    command -v "$1" >/dev/null 2>&1 &&
        "$1" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info < (3, 14) else 1)' >/dev/null 2>&1
}

if [[ -n "${OM_PYTHON:-}" ]]; then
    if ! om_supported_python "$OM_PYTHON"; then
        printf 'OM_PYTHON=%s غير متوفر أو غير مدعوم. استخدم Python 3.11–3.13، أو أزل OM_PYTHON للاختيار التلقائي.\n' "$OM_PYTHON" >&2
        exit 1
    fi
else
    OM_PYTHON=""
    for OM_CANDIDATE in "$OM_PROJECT_DIR/.venv/bin/python" python3 python3.12 python3.13 python3.11; do
        if om_supported_python "$OM_CANDIDATE"; then
            OM_PYTHON="$OM_CANDIDATE"
            break
        fi
    done
    if [[ -z "$OM_PYTHON" ]]; then
        printf 'لم يوجد Python 3.11–3.13 مناسب. تجهيز Python 3.12 داخل المشروع…\n'
        OM_UV="$OM_PROJECT_DIR/.bootstrap/bin/uv"
        if [[ ! -x "$OM_UV" ]]; then
            # --target installs only inside this project, including on managed system Python.
            if ! python3 -m pip install --target "$OM_PROJECT_DIR/.bootstrap" --no-deps 'uv==0.12.19'; then
                printf 'تعذر تجهيز uv. تحقق من الإنترنت ومن توفر python3-pip، ثم أعد bash setup.sh.\n' >&2
                exit 1
            fi
        fi
        export UV_PYTHON_INSTALL_DIR="$OM_PROJECT_DIR/.python"
        export UV_CACHE_DIR="$OM_PROJECT_DIR/.cache/uv"
        "$OM_UV" python install 3.12 --no-bin --no-config
        OM_PYTHON="$("$OM_UV" python find 3.12 --managed-python --no-config)"
        if ! om_supported_python "$OM_PYTHON"; then
            printf 'تعذر العثور على Python المدعوم بعد التنزيل.\n' >&2
            exit 1
        fi
    fi
fi

printf 'Python المختار: %s\n' "$OM_PYTHON"
if [[ -e "$OM_PROJECT_DIR/.venv" ]]; then
    if ! om_supported_python "$OM_PROJECT_DIR/.venv/bin/python"; then
        printf 'البيئة .venv الحالية غير صالحة. أعد تسميتها للاحتفاظ بها ثم أعد التجهيز.\n' >&2
        exit 1
    fi
else
    "$OM_PYTHON" -m venv "$OM_PROJECT_DIR/.venv"
fi
"$OM_PROJECT_DIR/.venv/bin/python" -m pip install -r "$OM_PROJECT_DIR/requirements.txt"
"$OM_PROJECT_DIR/.venv/bin/python" -m pip check
printf 'اكتمل تجهيز المشروع. التشغيل: bash "%s/run.sh" --symbol GSPC\n' "$OM_PROJECT_DIR"
