# ClipForge Studio

A local video editor with project storage, an interactive single-source timeline,
captioned MP4 export and optional local AI. No watermark or paid API is required.
This build extends the existing project; see [engineering status](ENGINEERING.md)
and [test evidence](TEST_RESULTS.md) for verified behavior and remaining gates.

## First run on a Mac

Keep the extracted folder together and double-click **Open ClipForge.command**.
It discovers Python/FFmpeg in both Apple Silicon and Intel Homebrew locations. If
prerequisites are missing and you already use Homebrew, it asks before installing
`python@3.12` and/or `ffmpeg`. Declining changes no system packages. Homebrew itself
and administrator privileges are never installed/requested automatically.

If Homebrew is unavailable, install Python 3.10–3.12 and FFmpeg/FFprobe first using
your preferred supported installer. With existing Homebrew:

```bash
brew install python@3.12 ffmpeg
```

The Python setup creates `.venv`, installs pinned core packages (including bundled
OpenCV face detection), checks imports/versions and opens the browser only after
the server becomes ready. No AI weights are downloaded. Keep Terminal open;
Control+C stops the launcher and its child server. If permissions were lost during
copying, run `chmod +x *.command` inside the folder. Use Finder's right-click → Open
only if you trust the downloaded files.

Core native-wheel minimums: macOS 11 Apple Silicon / macOS 12 Intel. Optional AI
stack: macOS 13+. These package compatibility choices and simulated shell behavior
were tested; **the app has not been run on a physical Mac in this environment**.

**Repair ClipForge.command** checks pinned packages, native vision imports, bundled
face detector, FFmpeg/FFprobe, writable storage, port availability and a disposable
real render. It does not install or delete anything. Save a new report with
`.venv/bin/python repair.py --output diagnostic-report.json`.

Manual first run / Linux (with Python and FFmpeg already installed):

```bash
python3 bootstrap.py --launch
```

After setup: `.venv/bin/python launcher.py`. Set `CLIPFORGE_PORT` to choose another
port, `CLIPFORGE_NO_BROWSER=1` for headless use, or `CLIPFORGE_FFMPEG` /
`CLIPFORGE_FFPROBE` for explicit executable paths. Servers bind only to loopback.

## Edit and export

1. Upload/drop local footage and mark source in/out points.
2. Add selected ranges to the timeline. Drag edges to trim, split at the playhead,
   delete or reorder clips. Use the move buttons as an alternative to dragging.
3. Zoom or fit the sequence. Build its real audio waveform when wanted; thumbnails
   are actual cached source frames, not illustrative graphics.
4. Choose framing, captions, audio processing and a creator preset in the inspector.
5. Save the timeline and optionally render a low-resolution draft, then export MP4.

Shortcuts outside text inputs: Space play/pause, S split, Delete remove,
Ctrl/Command-Z undo, Shift-Ctrl/Command-Z redo, arrows step the playhead and Shift
arrows step one second. Undo is session-local; the saved sequence survives restart.
Unsaved sequence changes prompt before project switching/page exit.

This is a **single-source sequence editor**, with linked video/audio ranges, not a
multi-camera or independent multi-track NLE. Browser playback seeks between source
ranges and may pause briefly; final exports are assembled into a continuous MP4.
Final vertical output is 1080×1920; vertical drafts are 360×640. Landscape exports
retain source dimensions; landscape drafts use width 640.

### Reframing

**Preserve full image** adds intentional bars when needed, **Center crop** uses a
fixed crop, and **Smart faces** runs local face detection only on selected ranges.
Smart mode matches faces over time and uses experimental mouth-motion plus audio
activity to suggest a speaking face. Ambiguous/missing faces fall back to full-image
fit; a smoothed/interpolated crop is used only when the sampled interval looks safe.
This is not learned speaker diarization or a guarantee that every face is detected.
Review drafts and override the decision whenever needed.

Software H.264/AAC is the tested encoding path. Apple VideoToolbox is available as
an explicit option if FFmpeg advertises it; physical Mac execution is not verified.
Every export must pass duration, dimensions, frame rate, audio-presence and complete
decode checks. Stream timing warnings are reported. Those checks do not establish
perceptual lip sync, accurate transcription or editorial excellence.

### Captions and audio

Enable captions after transcription or manual transcript entry. Choose font, size,
text/highlight colors, position, plain/subtle fade/word highlight. Word highlight
requires real word timestamps and refuses segment-only text rather than inventing
alignment. Segment-only captions can use proportional subdivision for readable
blocks. Transcript JSON corrections discard previous word alignment.

Audio options are explicit: measured two-pass −16 LUFS normalization, conservative
noise reduction and short 20 ms edge fades. Preview denoising on real speech before
using it. The Football Podcast Professional preset uses restrained framing/captions;
custom styles and clip settings can be saved locally.

## Local transcription and semantic review

Run **Enable AI.command** or:

```bash
.venv/bin/python -m pip install -r requirements-ai.txt
```

| Mode | Model | Approximate weights |
| --- | --- | --- |
| Fast | tiny | 75 MB |
| Balanced | base | 145 MB |
| Maximum quality | small | 485 MB |

The UI shows model sizes and requires consent before fetching uncached weights.
Models are shared between projects and can be explicitly removed when analysis is
idle. CPU int8 is preferred; supported float32 is a fallback. This Faster-Whisper
backend does not provide Metal/MPS transcription. Performance estimates appear only
after measured chunks. Audio is extracted in bounded 180-second cores with context
overlap; completed chunks/transcripts are content/settings cached and reused on retry.

**Transcribe audio** produces text. **Analyze meaning & context** separately uses an
installed local Ollama model at `127.0.0.1:11434`. Install/start Ollama and select a
local model of a size suitable for your hardware using its supported setup, then
click Refresh local models. ClipForge never pulls an LLM automatically, and rejects
cloud-backed model aliases. Model weights have disk/RAM costs; no paid provider is
used as a fallback.

Semantic review summarizes bounded windows and global context, generates grounded
candidate ranges, reviews qualifications/surrounding context, and diversifies results.
Scores are model preferences requiring review, not proof of quality or fidelity.
**Quick heuristics** is an explicit optional alternative and does not analyze meaning.
Ratings update bounded local reranking weights, not a language model's parameters.
Transcript changes invalidate recommendations; rerun review after corrections.

### Current model-host blocker in this cloud environment

Hugging Face access still returns proxy HTTP 403. Authorized hosts were saved in the
environment draft: `huggingface.co`, `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.hf.co`,
`cas-bridge.xethub.hf.co`, `cas-server.xethub.hf.co`. Review/save in environment settings
and publish to activate. Saving a draft alone does not change the running policy.
No new token is required for the public tiny model. No alternate access route is used.

A real speech verification gate and public JFK fixture are included:

```bash
.venv/bin/python tools/verify_transcription.py \
  --source tests/fixtures/jfk.flac --reference tests/fixtures/jfk.txt --allow-download
```

This explicitly consents to approximately 75 MB of weights. It checks actual output
against reference words. Exit 2 means host access is blocked, not a passed model test.
Here the gate is still blocked, and no real Ollama model is running: **real speech and
semantic-quality acceptance remain unverified**.

## Storage, imports and recovery

Projects, SQLite jobs/caches, presets and models live under `data/`. Select another
writable location using `CLIPFORGE_DATA_DIR` before launch. Stop the app and back up
all data/SQLite files before moving them; automatic migration is not implemented.

The storage panel separates originals, models, temporary files, thumbnails/previews,
exports and metadata. The free-space reserve defaults to 256 MiB (minimum 64 MiB).
Checks occur during upload/render and between audio chunks. Low-space work pauses;
originals and completed exports are never silently deleted. Multipart uploads may
also spool to the OS temporary directory, which needs sufficient free space.

Background jobs persist. Interrupted jobs are marked on restart; retry transcription
to reuse completed chunks. Rendering restarts rather than resuming a partial MP4.
Intermediate timeline parts and working audio are cleaned up. Run one server per
data directory.

Local uploads always remain available. Optional public direct-media URL imports use
HTTP(S) streaming with validation of public addresses/redirect targets. YouTube
extraction remains unavailable; import failures preserve the project and allow a
local authorized source to be supplied. No DRM or platform access controls are bypassed.

Local access is the implemented mode. Do not forward the server publicly: remote
and hosted modes still require a separate authenticated/encrypted architecture.

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt -r requirements-ai.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python repair.py
.venv/bin/python tools/stress_long.py
```

Browser tests use existing Chromium/Chrome, including standard Mac Chrome paths.
Set `CLIPFORGE_CHROMIUM` to an explicit browser executable. If none exists the UI
gate is explicitly skipped; it ran and passed here. No browser is downloaded by tests.
The long-media stress test is separate from the pytest count and uses synthetic media
and a controlled transcription engine. Read its memory/timing limits in ENGINEERING.md.

The GitHub remote was initially empty. Uploaded source and improvements are committed
locally; nothing was pushed. Fresh-task restoration of local-only commits has not been
verified. The downloadable ZIP includes project files/fixtures, not environments,
private media, caches, model weights or credentials.
