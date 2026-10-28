# Validation evidence

Current cloud environment: Linux x86_64, Python 3.12.14, FFmpeg/FFprobe 7.1.5,
OpenCV 4.10.0, NumPy 2.2.5, Faster-Whisper 1.1.1, CTranslate2 4.6.0.

- **41 passed**, no failures or skips, in the full pytest run. One upstream Starlette/AnyIO deprecation warning.
- Actual Chromium: upload → trim/split/reorder → undo/redo → save → waveform → transcript correction → fade-captioned timeline export → download → reopen persisted timeline/history.
- Actual desktop screenshot and mobile-width overflow check; no JavaScript page errors in the browser smoke test.
- Actual FFmpeg frames: rendered white/fade captions and karaoke-highlight pixels, reordered timeline picture content, moving crop content.
- Actual audio: an exported normalized tone measured within 1 LUFS of −16 LUFS. Conservative denoising and edge fades rendered successfully.
- Actual OpenCV face detection on the public-domain NASA fixture and a video encoded from it. Controlled two-face motion/silence tests validate tracker mechanics, not real podcast speaker recognition.
- Local LLM HTTP schema/transport, grounding/rejection, hierarchy and cache tests use controlled responses. No real semantic inference occurred.
- Fresh final-pinned first-run installation passed in a new directory with spaces, followed by a repeat setup; no broken packages. Isolated shell/TTY tests exercised both Homebrew consent and decline paths without installing OS software.
- 31-minute synthetic source: 11 bounded real audio extractions, completed-cache reuse, final full-size export and download passed. Separate memory report: `artifacts/long-video.json`.
- Real Faster-Whisper no-download preflight executed with the installed native package; no weights were downloaded without consent.
- Real inference gate: **BLOCKED**, exit 2, Hugging Face HTTPS CONNECT returned proxy HTTP 403. `jfk.flac` is available; the speech model is not. No speech accuracy/WER success is claimed.
- macOS wheel metadata checked for the selected native stack; physical Mac startup, Homebrew installation, VideoToolbox, Safari and real podcast editorial quality remain unverified.

Machine-readable suite output: `artifacts/test-results.xml`. The stress test is a separate
executed command, not included in the pytest test count. See ENGINEERING.md for limits.
