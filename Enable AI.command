#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
trap 'code=$?; if [ -t 0 ]; then read -r -p "Press Return to close..."; fi; exit "$code"' EXIT
if [ ! -x .venv/bin/python ]; then echo 'Open ClipForge once to create its Python environment.'; exit 1; fi
.venv/bin/python -c 'import platform,sys; v=platform.mac_ver()[0]; sys.exit("The optional AI stack requires macOS 13 or newer. Core manual editing/export remains available." if platform.system()=="Darwin" and v and int(v.split(".")[0])<13 else 0)'
.venv/bin/python -m pip install -r requirements-ai.txt
.venv/bin/python -c 'from faster_whisper import WhisperModel'
.venv/bin/python -m pip check
echo 'AI packages installed. Models are downloaded separately with explicit consent in the app.'
