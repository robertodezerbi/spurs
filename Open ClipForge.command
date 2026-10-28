#!/bin/bash
set -e
cd "$(dirname "$0")"
echo '🎬 ClipForge — starting your local video studio'
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo 'FFmpeg is required. On a Mac with Homebrew, run: brew install ffmpeg'
  echo 'Then double-click this launcher again.'
  read -r -p 'Press Return to close...'
  exit 1
fi
if [ ! -d .venv ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3; else echo 'Install Python 3.10+ from python.org'; read -r -p 'Press Return...'; exit 1; fi
  "$PY" -m venv .venv
fi
source .venv/bin/activate
if ! python -c 'import fastapi,uvicorn,multipart' >/dev/null 2>&1; then
  echo 'Installing required local packages (first launch only)...'
  python -m pip install -r requirements.txt
fi
if ! python -c 'import faster_whisper' >/dev/null 2>&1; then
  echo 'AI transcription is optional and not installed yet.'
  echo 'To enable it later: source .venv/bin/activate && pip install -r requirements-ai.txt'
fi
(sleep 2; open 'http://127.0.0.1:8000') &
echo 'Your browser will open shortly. Keep this Terminal window open while using ClipForge.'
echo 'Press Control+C to stop.'
exec python -m uvicorn app:app --host 127.0.0.1 --port 8000
