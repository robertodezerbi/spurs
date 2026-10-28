#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo 'Please open ClipForge once before enabling AI.'; read -r -p 'Press Return...'; exit 1; fi
source .venv/bin/activate
python -m pip install -r requirements-ai.txt
echo 'AI installed. Restart ClipForge using Open ClipForge.command.'
read -r -p 'Press Return to close...'
