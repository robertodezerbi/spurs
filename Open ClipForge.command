#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# Finder does not inherit your Terminal PATH. Cover native and Intel Homebrew.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
trap 'code=$?; if [ "$code" -ne 0 ]; then echo "ClipForge could not start. Review the error above or run Repair ClipForge.command."; if [ -t 0 ]; then read -r -p "Press Return to close..."; fi; fi' EXIT
PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(not ((3,10) <= sys.version_info[:2] < (3,13)))' 2>/dev/null; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then echo 'Install Python 3.10–3.12 from python.org or Homebrew (brew install python@3.12).'; exit 1; fi
if [ ! -x .venv/bin/python ]; then "$PY" -m venv .venv; fi
.venv/bin/python -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,13), "Recreate .venv with Python 3.10–3.12"'
.venv/bin/python -c 'from runtime import diagnostics; import json,sys; r=diagnostics("."); print(json.dumps(r,indent=2)); sys.exit(not r["ok"])'
# Reinstall only if this requirements file changed or dependency validation fails.
STAMP="$(.venv/bin/python -c 'import hashlib; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ ! -f .venv/clipforge-requirements ] || [ "$(cat .venv/clipforge-requirements)" != "$STAMP" ] || ! .venv/bin/python -m pip check >/dev/null 2>&1 || ! .venv/bin/python -c "import fastapi,uvicorn,multipart" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip check
  echo "$STAMP" > .venv/clipforge-requirements
fi
.venv/bin/python launcher.py
