#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
trap 'code=$?; if [ "$code" -ne 0 ]; then echo "ClipForge could not start. Review the error above or run Repair ClipForge.command."; if [ -t 0 ]; then read -r -p "Press Return to close..."; fi; fi' EXIT
PY=""
for candidate in .venv/bin/python python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(not ((3,10) <= sys.version_info[:2] < (3,13)))' 2>/dev/null; then PY="$candidate"; break; fi
done
if [ -z "$PY" ] || { ! command -v ffmpeg >/dev/null 2>&1 && [ -z "${CLIPFORGE_FFMPEG:-}" ]; } || { ! command -v ffprobe >/dev/null 2>&1 && [ -z "${CLIPFORGE_FFPROBE:-}" ]; }; then
  if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1 && [ -t 0 ]; then
    echo 'First run needs Python 3.12 and FFmpeg. This installs software using your existing Homebrew; it does not install Homebrew or download AI models.'
    read -r -p 'Install missing prerequisites with Homebrew now? [y/N] ' answer
    case "$answer" in
      y|Y|yes|YES)
        if [ -z "$PY" ]; then brew install python@3.12; PY=python3.12; fi
        if { ! command -v ffmpeg >/dev/null 2>&1 && [ -z "${CLIPFORGE_FFMPEG:-}" ]; } || { ! command -v ffprobe >/dev/null 2>&1 && [ -z "${CLIPFORGE_FFPROBE:-}" ]; }; then brew install ffmpeg; fi
        ;;
      *) echo 'No system packages changed. Install Python 3.10–3.12 and FFmpeg, then reopen ClipForge.'; exit 1;;
    esac
  else
    echo 'Install Python 3.10–3.12 and FFmpeg/FFprobe first. On a Mac with existing Homebrew: brew install python@3.12 ffmpeg'
    echo 'Homebrew itself is never installed automatically. See README.md for other installation options.'
    exit 1
  fi
fi
"$PY" bootstrap.py --launch
