# ClipForge engineering status

Development continued from the existing commits and 18-test baseline. Existing uploads,
projects, data format and local HTTP workflow were retained. No repository was rebuilt,
no Git worktree was created and nothing was pushed to the empty GitHub remote.

## Current priorities and evidence

| Priority | Implemented and exercised | Still unverified or blocked |
| --- | --- | --- |
| macOS first run | `bootstrap.py` creates an isolated environment, verifies pinned versions and native imports, preserves incomplete environments, and supports repeat setup. The Finder launcher handles both Homebrew prefixes and offers an explicit install/decline prompt for missing prerequisites. Fresh Linux installation, paths with spaces, repeat setup and isolated Mac shell/TTY simulations passed. | No macOS machine is attached. Real Finder, quarantine, Homebrew, Intel/Apple Silicon runtime and VideoToolbox execution cannot be certified here. |
| Authorized model access | Existing Hugging Face destination rules remain in the saved environment draft. An explicit real-inference gate probes the authorized route and reports a blocker with exit code 2. No credentials, alternate model mirrors, proxy bypasses or disabled TLS were used. | Running environment remains revision 1 without the new hosts. HTTPS CONNECT returns HTTP 403. Settings must be applied before uncached weights can be fetched. |
| Faster-Whisper | The real installed package imports, checks CPU compute compatibility, honors no-download consent, caches chunks and exposes real word timestamps. A JFK speech fixture and word-error-rate gate are included. | The gate is **blocked**, not passed: real weights are unavailable. Speech accuracy, real Whisper runtime, word alignment and model performance are not verified. |
| Semantic selection | An opt-in local Ollama pipeline maps bounded transcript windows, builds hierarchical context summaries, generates segment-grounded candidates, reviews surrounding/global context, caches responses and diversifies results. Cloud-backed aliases are rejected. Heuristics are now an explicit separate choice; transcription/corrections never silently substitute them. Grounding, caching, malformed candidate rejection and actual local HTTP contracts have controlled tests. | No local Ollama service/model is installed here. These are integration/contract tests, not real model inference or editorial-quality tests. Model context judgments are labeled for manual review. |
| Faces and reframing | Real OpenCV Haar detection passed on a NASA portrait and an encoded portrait video. Temporal face matching and an experimental audio-gated mouth-motion signal passed controlled speaker-switch/silence tests. Smart framing chooses conservative fit on uncertainty. Render tests verify actual moving crop pixels and valid vertical output. | This is not learned audiovisual diarization. Real multi-speaker podcast accuracy, identity continuity through occlusions, profiles, smoothness and editorial camera choices remain unverified. |
| Interactive timeline | Single-source clip sequence with trim handles, split, delete, drag/button reordering, zoom/fit, playhead/scrubbing, linked video/audio tracks, real thumbnails/waveform, keyboard shortcuts, undo/redo, saved edit decisions and unsaved-edit warnings. Real Chromium exercised editing, save/reopen and captioned sequence export. Output pixel tests verify clip order. | Multi-source/multi-camera editing, independent audio tracks, transitions and frame-accurate browser preview are not implemented. Browser preview seeks between source ranges; final exports use an assembled MP4. |
| Captions and audio | ASS plain/fade/word-highlight rendering; fonts, text/highlight colors, safe positioning and bounded groups. Real output pixels verify fade text and karaoke color. Karaoke refuses segment-only timing. Two-pass measured −16 LUFS normalization, optional conservative denoising and 20 ms edge fades. Exported tone audio measured within 1 LUFS of target. | Word timing fixtures are supplied, not inferred by a real Whisper model in these tests. Real speech/denoising artifacts and Mac font availability need listening/visual review. |
| Longer media | A real 31-minute low-complexity MP4 was uploaded, eleven real bounded audio chunks extracted, cache reuse checked, and a final 1080×1920 MP4 exported from the final five seconds. Media decode is streamed; intermediate chunks and timeline parts are removed. Storage accounting avoids double-counting hard-linked parts. | This is not a high-resolution or complex podcast benchmark and does not measure real model inference. Practical capacity remains bounded by hardware and storage. |
| UI | Studio layout with library, source monitor, inspector and timeline. Actual desktop browser export test and a narrow-viewport overflow check are included; screenshots are generated. | Broader accessibility, Safari and physical mobile device tests remain. |
| End-to-end validation | Regression suite grew from 18 to 41 tests. Includes real HTTP startup/shutdown, image/audio checks and browser editing → captioned MP4 download. No model-quality acceptance is inferred from controlled outputs. | CI definitions have not run on GitHub; no remote branch was pushed. Full directive acceptance is not met while the above gates remain open. |

## Long-media measurements

`tools/stress_long.py` generated 31 minutes of 160×90 video at 2 fps plus sine audio.
The source was 7,739,956 bytes. Eleven audio WAVs were extracted; the largest was
5,952,078 bytes (about 186 seconds at mono 16 kHz PCM). Completed work was reused on retry.
A five-second 1080×1920 export at the end of the source passed FFprobe, full decode and download.

Observed in this Linux run: 24,104,934 traced Python peak bytes; 81,522,688 process peak
RSS bytes; 207,302,656 largest-child peak RSS bytes. These are separate measurements,
not a sum of concurrent memory. Total fixture generation and checks took 8.57 seconds.
**None of this measures real Whisper speed**, because a controlled engine supplied the
text while FFmpeg performed real extraction. The JSON report is `artifacts/long-video.json`.

## Design and recovery details

- Heavy tasks remain serialized. Vision runs only on the selected export intervals.
- Single-source timeline parts render serially, concatenate and re-encode for consistent
  streams, validate before publication, and are removed on success/failure. This trades
  additional render time for bounded decoder concurrency and simpler recovery. Rendering
  is restarted after interruption; cached transcription chunks are reused.
- Metadata writes remain atomic. Transcript edits are refused while transcription or
  semantic analysis is active, to prevent an in-flight job overwriting corrections.
- Cached vision reports retain sampled coordinates and track metadata, never raw frames.
  Waveform extraction uses small PCM buffers and a fixed-size peak envelope.
- Semantic outputs must refer to real segment boundaries and pass finite score/length
  checks. This grounds timestamps; it does not prove the model preserves intended meaning.
- Missing local AI never triggers a paid/cloud provider. Ollama listing filters small
  remote manifests/cloud tags; selected model details are checked for remote backing.

## Regressions caught during this continuation

Browser testing found a Playwright polling helper incompatible with the existing strict
CSP. The test now uses direct DOM reads; app CSP was preserved. Output inspection caught
an invalid `.5` timestamp in a new test helper; it was corrected to `0.5`. A SQL quoting
mistake while hiding internal timeline parts was caught before delivery and replaced
with a parameterized query. The final repeated suite also caught a storage inventory race when SQLite removed its shared-memory file between stats. Inventory now uses one cached lstat result, tolerates concurrent cleanup, and has a deterministic regression test. The full suite passed after fixes.

OpenCV 4.11 required macOS 13 for both CPU families. Version 4.10.0.84 was selected and
revalidated to retain wheel support for macOS 11 Apple Silicon and macOS 12 Intel. This
is installation compatibility evidence, not an on-device runtime test. The optional
pinned AI stack still requires macOS 13+.
