# ClipForge — local video studio

This update starts from the seven uploaded project files. It restores the missing web interface and improves startup, rendering, diagnostics, persistence, and long-audio processing. Core upload, manual editing, captions, previews, and MP4 exports do not require paid services or model downloads.

## Open on a Mac

1. Keep all files together after extracting the project ZIP.
2. Install **Python 3.10–3.12** and **FFmpeg with FFprobe**. With existing Homebrew: `brew install python@3.12 ffmpeg`. Installing Homebrew itself is a separate system setup action; ClipForge does not install it or request administrator privileges.
3. Double-click **Open ClipForge.command**. If macOS blocks it, use Finder's right-click → Open only if you trust the files. If execute permissions were lost, run `chmod +x *.command` inside this folder.
4. Keep the Terminal window open. Control+C stops the server and its child process.

The launcher handles Apple Silicon `/opt/homebrew/bin` and Intel `/usr/local/bin`, checks Python and FFmpeg, creates an isolated `.venv`, installs core dependencies when requirements change, checks for port conflicts, and waits for an application health response before opening the browser. It binds only to `127.0.0.1`. Set `CLIPFORGE_PORT` to use another port. It does not expose a public website.

If startup fails, run **Repair ClipForge.command**. It checks Python, package consistency, FFmpeg/FFprobe, disk writing, port availability, and a disposable render. It never removes projects or installs packages. For a saved report: `.venv/bin/python repair.py --output diagnostic-report.json` (will not overwrite an existing file).

### Manual startup / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python launcher.py
```

FFmpeg and FFprobe must be installed by your OS package manager. Set `CLIPFORGE_FFMPEG` and `CLIPFORGE_FFPROBE` to explicit executable paths for custom installations. Use `CLIPFORGE_NO_BROWSER=1` in a headless environment.

## Workflow

Upload or drag in a local MP4/MOV/MKV/WebM/AVI/M4V. Set clip boundaries or mark the current playback time. Preview the selection, save clip settings, optionally correct the transcript, and render a draft or final MP4.

- Vertical framing defaults to **preserve full image**. It may add intentional bars, preserving subjects at the edges. Center crop is available and must be checked manually for cut-off faces.
- Draft previews use 360×640 vertical output; final vertical exports use 1080×1920. Landscape exports retain source size; landscape drafts use width 640.
- Software H.264/AAC is the tested encoder. Apple VideoToolbox is an explicit option when FFmpeg advertises it. Runtime errors are shown; it is not benchmarked or validated here on macOS.
- Captions require transcript segments that overlap the clip and FFmpeg's libass/subtitles filter. Whisper word timings produce short groups; manually entered segments use proportional timing if they need multiple caption blocks. Manual corrections are not claimed to have word alignment.
- Technical validation checks H.264 video, duration, dimensions, frame rate, source-audio retention, stream timing offsets, and complete decoding before allowing downloads. Warnings and limitations are returned with the job. These checks do **not** guarantee perceptual sync, accurate transcription, correct meaning, or editorial excellence.
- The Football Podcast Professional preset preserves the image, uses restrained captions, and adds no effects. Save custom presets and clip boundaries locally.

## Optional local transcription

Run **Enable AI.command** (or `.venv/bin/python -m pip install -r requirements-ai.txt`). The constrained native AI stack requires **macOS 13+**; binary-wheel availability was checked for Intel/Python 3.10 and Apple Silicon/Python 3.12. This is not an on-device runtime test. The core app is separate from this optional stack.

| Mode | Whisper model | Approximate weights | Strategy |
| --- | --- | --- | --- |
| Fast | tiny | 75 MB | CPU int8, beam 1 |
| Balanced | base | 145 MB | CPU int8, beam 3 |
| Maximum quality | small | 485 MB | CPU int8, beam 5 |

The interface shows model sizes and requires download consent for an uncached model. Packages and weights have additional disk costs. Cached models are shared across projects. The model panel allows explicit removal when no analysis is active. This Faster-Whisper backend does **not** support Metal/MPS; Mac architecture is detected without claiming unsupported acceleration.

Audio is extracted one bounded 180-second chunk at a time with three seconds of context on either side. Word midpoints assign overlap ownership; offsets are merged into source time. Actual model outputs can still vary at chunk boundaries and require review. SQLite caches completed chunks and transcripts using the source content, model, engine version, and analysis settings. Retrying interrupted analysis reuses completed chunks. ETA appears only after measured work; measurements include extraction/transcription and are stored with hardware facts.

Suggestions use sentence-end cues, opening-dependency cues, speech density, duration fit, and overlap suppression. They are **heuristics**, not semantic understanding or contextual verification. Useful/not-useful ratings update bounded local feature weights for reranking; they do not train Whisper or a language model.

## Imports and privacy

Public direct-media HTTP(S) URLs are an optional streaming import route. Standard ports only; private network addresses, embedded credentials, and private redirect targets are rejected. Proxy/TLS verification remains enabled. Live remote importing was not validated against an external video host; its streaming and failure paths have automated tests.

YouTube extraction is deliberately unavailable in this build. Import failures preserve the project, report the reason, and allow a local authorized source to be supplied. No DRM, access controls or authentication requirements are bypassed.

Local operation is the only implemented access mode. Cross-origin browser requests and non-local host headers are rejected. **Do not run a public reverse proxy or forward this port.** Private remote and hosted modes still require authentication, encrypted transport, authorization, and security testing before implementation. No paid AI APIs, analytics, authentication provider, or cloud storage are required.

## Storage and recovery

Projects live in `data/` by default. Set `CLIPFORGE_DATA_DIR` **before launching** to select a different writable storage location. Stop the app before moving data; back up the entire folder (including SQLite WAL files if present) and do not overwrite existing projects. This build does not perform automatic migration.

The dashboard separates originals, models, temporary files, previews, exports, and metadata/cache. Set the minimum free-space reserve in the UI (default 256 MiB, minimum 64 MiB). Space is checked during upload, before analysis/render, between chunks and during rendering. Low-space work pauses with an explicit error. An in-flight network upload may also use the OS temporary directory for multipart spooling; keep sufficient space there too.

Originals and completed exports are never silently deleted. Transient audio/render files are removed on completion/failure and after restart. Jobs persist in SQLite; unfinished jobs become **interrupted** on server restart. Retry analysis to resume from cached chunks; interrupted rendering is restarted, not resumed from a partial MP4. Run only one server process per data directory.

## Development and validation

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

The regression suite generates real test videos and tests upload → render → technical validation → download, caption burn-in, draft resolution, local HTTP startup/shutdown, storage failure, imports/fallback, persistence, cache reuse, overlap ownership, presets, transcript edits, and feedback weights. Controlled transcription engines test chunk/cache behavior; they do not validate speech accuracy. See `ENGINEERING.md` for phase status and remaining requirements.

Model access in this cloud environment is currently blocked by its network policy. Hugging Face destination additions and reusable installation/start instructions were saved in the environment draft; review/save in environment settings and publish to activate. Draft saving does not apply network changes or prove fresh-task restoration. The uploaded source is committed locally; the GitHub remote initially contained no commits or `main` branch. Nothing was pushed.
