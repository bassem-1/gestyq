#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v conda >/dev/null 2>&1 && conda env list | grep -q '^vision '; then
  exec conda run --no-capture-output -n vision python app.py
fi
exec python3 app.py
