# ClipForge — Local AI Video Clipper

A **working local-first MVP** with video upload, browser preview, manual clip selection, FFmpeg export, vertical cropping, and optional local AI transcription with heuristic clip suggestions and subtitle burn-in.

## Quick start

Install Python 3.10+ and **FFmpeg** (including ffprobe), both available on your PATH.

```bash
cd clipforge
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Upload a video, select start/end seconds, then Export MP4.

### Enable optional AI transcription

```bash
pip install -r requirements-ai.txt
```

Restart the server. Click **Analyze full video**. First use downloads an open-source Whisper model. The default is `base` on CPU; override with `WHISPER_MODEL=small` (or another supported model). Analysis may be slow for long videos. AI clip suggestions are ranked using transparent **speech density and duration heuristics**, not a full LLM semantic analysis. Captions use transcript segments, not word-level animation.

## Capabilities

- No arbitrary video-duration cap, export quota, subscription, or watermark.
- Uploads streamed in chunks to local disk; long files still require sufficient storage and processing time.
- Manual timestamps, clip preview, centered 9:16 crop, MP4 H.264/AAC export.
- Optional transcription, transcript display, automatic clip suggestions, basic subtitle burn-in.
- Projects saved in `data/` on your computer.

## Honest limitations

- This is **not yet an OpusClip equivalent**. It does not implement speaker tracking, automatic B-roll, word-by-word animated captions, a full timeline editor, sophisticated semantic clip ranking, or YouTube link import.
- Local use only. No authentication; **do not expose this server to the public internet**.
- Long files need free disk space and may take hours to transcribe or render. FFmpeg must include libx264 and the subtitles filter for caption burn-in.
- Cropping is centered, not face-tracked. Browser playback support for source MOV/MKV/AVI depends on browser codecs; export still works.
- The source-video endpoint does not implement special seeking optimizations beyond standard file serving.
- Only upload media you have rights or permission to edit.

## Troubleshooting

- `ffmpeg not found`: install FFmpeg and make sure `ffmpeg` and `ffprobe` work in your terminal.
- AI analysis unavailable: install `requirements-ai.txt`, then restart the server.
- Caption export fails: ensure your FFmpeg has the `subtitles` filter (`ffmpeg -filters | grep subtitles`).

## Run automated smoke test

```bash
pip install httpx pytest
pytest -q
```

## One-click Mac launcher

After extracting the ZIP, **double-click `Open ClipForge.command`**. It opens the website automatically in your browser, creates a local Python virtual environment and installs the core Python dependencies on first run. You need Python 3.10+ and FFmpeg installed first. On macOS, if the system blocks the launcher, right-click the file and choose **Open** (only if you trust the downloaded code). Keep its Terminal window open while editing. Optional AI transcription requires a separate one-time install with `pip install -r requirements-ai.txt` inside `.venv`.

The website is local at `http://127.0.0.1:8000`, not a publicly hosted URL. The launcher does not deploy anything online.
