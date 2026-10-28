#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
trap 'code=$?; if [ -t 0 ]; then read -r -p "Press Return to close..."; fi; exit "$code"' EXIT
if [ ! -x .venv/bin/python ]; then echo 'No Python environment. Open ClipForge first; this repair utility does not install or remove files.'; exit 1; fi
.venv/bin/python repair.py
