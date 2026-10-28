# Engineering record

## Baseline audit

The uploaded baseline could not import: it mounted a missing `static/` directory. Finder's PATH omitted common Homebrew locations; startup opened the browser on a timer instead of waiting for readiness. FFmpeg success alone marked exports complete. Jobs lived only in a dictionary, parallel threads were unbounded, and captions could be silently omitted. Tests covered one short uncaptioned render and assumed an installed FFmpeg.

The original uploaded files are preserved in the first local Git commit. Subsequent commits isolate stability, persistence/analysis, and import/compatibility improvements. The remote was empty; local commits were not pushed.

## Phase status

| Phase | Implemented and exercised | Remaining acceptance work |
| --- | --- | --- |
| 1 — Stability | Portable FFmpeg/FFprobe discovery, launch health/port checks, missing UI restored, bounded worker, persistent jobs, real MP4 validation, live HTTP upload/export/shutdown test | Run launch/export on an actual Intel or Apple Silicon Mac; verify the user's original failing setup |
| 2 — Intelligence | Opt-in Faster-Whisper integration, three modes, audio chunk ownership, reusable caches, measured timing, heuristic reranking, real feedback weights | Download a real model and run speech accuracy tests once access is available; semantic topic/speaker/context analysis and stronger candidate-only models are not implemented |
| 3 — Editing quality | Full-image vertical framing, explicit center crop, timed readable caption groups, manual correction, restrained preset, FFprobe/decode QA | Active-speaker/face tracking, smoothed motion, split-screen, perceptual audio sync and black-frame/gap analysis are not implemented |
| 4 — Editing studio | Manual boundaries/preview, saved edits and presets, transcript JSON editor, draft renders | Multi-track graphical timeline, richer font/color/audio controls and edit-decision history are not implemented |
| 5 — Performance | Serial heavy worker, bounded audio extraction, completed-chunk resume, source/model/settings caches, model inventory/removal, storage reserve checks and category dashboard | Real Mac benchmarks, automatic model/acceleration selection, processing priorities, hierarchical semantic analysis, configurable retention and actual very-long-video stress tests remain |
| 6 — Polish | One-click/AI/repair launchers, explicit failures and model consent, browser labels, keyboard-accessible native controls, privacy headers | On-device accessibility/browser tests, signed/notarized Mac packaging, authenticated private remote and hosted modes remain |

Do not treat this table's implemented portions as completion of the entire directive. No real Whisper output, Metal, VideoToolbox runtime, speaker tracking, semantic ranking, or Mac performance claim has been verified. No arbitrary video-duration check exists, but the largest executed render is short test footage; unlimited practical capacity is not asserted.

## Regressions found and fixed during this update

- Stored feedback JSON was read as a mapping without decoding it. A regression test caught this; stored features are now decoded before updating weights.
- Faster-Whisper 1.1.1 imports `requests` without declaring it in its wheel metadata. Explicitly pinned and verified the import.
- Latest PyAV did not provide the checked Intel Mac/Python 3.10 wheel. Constrained native AI dependencies to a wheel-compatible stack and reran the Linux suite.
- SIGTERM previously could leave the launcher's child server alive. The real-server test now requires the port to close after the launcher stops.

## Validation boundaries

The generated video tests verify rendering and transport; they cannot assess football clip quality or real speech accuracy. Controlled speech-engine tests exercise extraction, time offsets, caches, resume, and timings without pretending to run Whisper. All output is local, watermark-free H.264/AAC; no service performs rendering or analysis remotely.

This environment uses Linux. Mac wheel availability and shell syntax checks are evidence about installation choices, not substitutes for Mac runtime tests. Hugging Face HTTPS access returned proxy HTTP 403, so speech-model validation remains an external blocker. It is recorded in the saved cloud network draft, rather than bypassed.
