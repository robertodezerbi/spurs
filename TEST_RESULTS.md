# Validation evidence

Current cloud run: Linux x86_64, Python 3.12.14, FFmpeg/FFprobe 7.1.5.

- `.venv/bin/python -m pytest -q`: **18 passed**, no failed or skipped tests. One upstream Starlette/AnyIO deprecation warning.
- Real Uvicorn server startup, HTTP upload, captioned MP4 export/download and clean parent/child shutdown passed.
- Real captioned and uncaptioned vertical H.264/AAC files passed FFprobe and full decode validation. Separate draft output passed 360×640 validation.
- `.venv/bin/python repair.py`: passed package consistency, writable storage and a disposable render.
- `.venv/bin/python -m pip check`: no broken requirements.
- Actual `from faster_whisper import WhisperModel` import passed with the constrained dependency stack.
- `bash -n` passed all three Mac launchers; `node --check static/app.js` passed. No browser automation was run.
- Native AI wheel availability checked for macOS 13 Intel/Python 3.10 and macOS 13 Apple Silicon/Python 3.12. Mac binaries were not executed.
- Real speech-model download **blocked**: HTTPS CONNECT to huggingface.co returned proxy HTTP 403. Model-host additions were saved in the cloud configuration draft, not applied to this running instance.
- Chunk ownership, caching, resume and ranking tests use controlled engine outputs. They are not speech-recognition or semantic-quality acceptance tests.
- macOS runtime, VideoToolbox hardware encoding, real Whisper speech accuracy, very-long-video resource consumption, speaker tracking and editorial quality remain unverified. The complete directive's acceptance criteria are not met yet; see ENGINEERING.md.
