"""ClipForge's local HTTP API. Heavy work runs in a bounded background queue."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from runtime import executable, run, media_info, validate_export, diagnostics
from store import Store
from analysis import MODES, model_inventory, model_path, transcribe, rank_candidates

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('CLIPFORGE_DATA_DIR', str(ROOT / 'data'))).expanduser().resolve()
DATA.mkdir(parents=True, exist_ok=True)
MODELS = DATA / '_models'; MODELS.mkdir(exist_ok=True)
DB = Store(DATA / 'clipforge.sqlite3')
WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix='clipforge')
LOCK = threading.RLock()
LOG = logging.getLogger('clipforge')
RESERVE = 256 * 1024 * 1024
PRESETS = {
    'Football Podcast Professional': {'vertical': True, 'framing': 'fit', 'captions': True,
        'caption_font_size': 18, 'caption_color': '&H00FFFFFF', 'encoder': 'software',
        'description': 'Full image preserved, restrained captions, natural cuts, no transitions or zoom effects.'},
    'Clean landscape': {'vertical': False, 'framing': 'fit', 'captions': False,
        'caption_font_size': 18, 'caption_color': '&H00FFFFFF', 'encoder': 'software'}
}


@asynccontextmanager
async def lifespan(app):
    DB.interrupt_jobs()
    # Only ephemeral working files are cleaned. Originals, models and exports survive.
    for project in DATA.iterdir():
        if re.fullmatch('[a-f0-9]{32}', project.name) and (project / 'tmp').is_dir():
            shutil.rmtree(project / 'tmp')
    yield


app = FastAPI(title='ClipForge — Local Video Clipper', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.middleware('http')
async def local_only(request: Request, call_next):
    # A local app has no remote login. Reject non-loopback hosts and browser origins
    # rather than exposing private videos accidentally through --host 0.0.0.0.
    from fastapi.responses import JSONResponse
    hosts = {'127.0.0.1', 'localhost', '::1', 'testserver'}
    if request.url.hostname not in hosts:
        return JSONResponse({'detail': 'Remote access is disabled. Use the local launcher.'}, status_code=403)
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc != request.url.netloc:
            return JSONResponse({'detail': 'Cross-origin requests are disabled'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'"
    return response


def probe(path):
    info = media_info(path)
    duration = float(info['format'].get('duration', 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Media duration is missing or invalid')
    return {'duration': duration, 'streams': info.get('streams', [])}


def folder(pid):
    if not re.fullmatch(r'[a-f0-9]{32}', pid):
        raise HTTPException(400, 'Invalid project ID')
    directory = DATA / pid
    if not directory.is_dir():
        raise HTTPException(404, 'Project not found')
    return directory


def metadata(directory):
    return json.loads((directory / 'project.json').read_text())


def save_meta(directory, value):
    temporary = directory / ('meta-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(directory / 'project.json')


def patch_meta(directory, **changes):
    with LOCK:
        value = metadata(directory); value.update(changes); save_meta(directory, value)
    return value


def ensure_space(required=0):
    free = shutil.disk_usage(DATA).free
    reserve = DB.setting('storage_reserve_bytes', RESERVE)
    if free < required + reserve:
        raise OSError(f'Low storage: need {required + reserve:,} free bytes including safety reserve; '
                      f'{free:,} available. Free space or move CLIPFORGE_DATA_DIR, then retry. Originals are preserved.')


@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/health')
def health():
    return {'application': 'clipforge', 'status': 'ok'}


@app.get('/api/diagnostics')
def diagnose():
    result = diagnostics(DATA)
    result.update(data_directory=str(DATA), models=model_inventory(MODELS),
                  benchmarks={c['model']: DB.setting('benchmark:' + c['model']) for c in MODES.values()},
                  remote_access='disabled', active_worker_limit=1)
    return result


@app.post('/api/upload')
def upload(file: UploadFile = File(...)):
    # Sync endpoint: multipart reads, disk writes and FFprobe do not block the event loop.
    suffix = Path(file.filename or 'video.mp4').suffix.lower()
    if suffix not in ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'):
        raise HTTPException(400, 'Unsupported video format')
    pid = uuid.uuid4().hex; directory = DATA / pid; directory.mkdir()
    dest = directory / ('source' + suffix)
    try:
        digest = hashlib.sha256()
        with dest.open('wb') as target:
            while chunk := file.file.read(4 * 1024 * 1024):
                ensure_space(len(chunk)); target.write(chunk); digest.update(chunk)
        info = probe(dest)
        if not any(s.get('codec_type') == 'video' for s in info['streams']):
            raise ValueError('File has no video stream')
        value = {'id': pid, 'name': Path(file.filename or 'video').name, 'source': dest.name,
                 'duration': info['duration'], 'source_hash': digest.hexdigest(),
                 'transcript': None, 'suggestions': [], 'edits': {}}
        save_meta(directory, value)
        return value
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    finally:
        file.file.close()


@app.get('/api/projects')
def projects():
    result = []
    for directory in DATA.iterdir():
        if (directory / 'project.json').exists():
            try:
                result.append(metadata(directory))
            except (OSError, ValueError):
                LOG.exception('Cannot load project %s', directory.name)
    return result


@app.get('/api/projects/{pid}')
def project(pid: str):
    return metadata(folder(pid))


@app.get('/api/projects/{pid}/source')
def source(pid: str):
    directory = folder(pid); name = metadata(directory)['source']
    if not name: raise HTTPException(409, 'Import has not completed. Upload a local video instead.')
    return FileResponse(directory / name)


class ClipRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    vertical: bool = True
    framing: Literal['fit', 'center'] = 'fit'
    captions: bool = False
    preview: bool = False
    caption_font_size: int = Field(default=18, ge=12, le=32)
    caption_color: str = Field(default='&H00FFFFFF', pattern=r'^&H[0-9A-Fa-f]{8}$')
    encoder: Literal['software', 'hardware'] = 'software'
    title: str = Field(default='clip', max_length=200)


def srt_time(seconds):
    ms = round(seconds * 1000); hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{sec:02},{ms:03}'


def captions_for(transcript, start, end):
    import textwrap
    lines = []; timings = []
    for segment in transcript:
        words = segment.get('words') or []
        # Word timestamps, when present, allow short readable timed groups.
        groups = [words[i:i+6] for i in range(0, len(words), 6)] if words else []
        cues = [{'start': g[0]['start'], 'end': g[-1]['end'], 'text': ''.join(w['word'] for w in g).strip()} for g in groups] if groups else [segment]
        for cue in cues:
            a, b = max(start, float(cue['start'])), min(end, float(cue['end']))
            if b <= a:
                continue
            # SRT cannot safely represent embedded ASS/HTML control sequences.
            text = re.sub(r'<[^>]*>|\{[^}]*\}', '', cue['text']).replace('\\', '').replace('-->', '→')
            wrapped = textwrap.wrap(text, width=32)
            # Long segment captions are divided into <=2 lines per cue, proportionally.
            blocks = ['\n'.join(wrapped[i:i+2]) for i in range(0, len(wrapped), 2)]
            for index, block in enumerate(blocks):
                x = a + (b-a)*index/len(blocks) - start
                y = a + (b-a)*(index+1)/len(blocks) - start
                lines.extend([str(len(timings)+1), f'{srt_time(x)} --> {srt_time(y)}', block, ''])
                timings.append((x, y))
    return '\n'.join(lines), timings


def update_job(jid, **changes):
    DB.update_job(jid, **changes)
    LOG.info('job=%s state=%s', jid, changes.get('status', 'updated'))


def render_worker(pid, jid, req):
    directory = folder(pid); out = directory / (('preview-' if req.preview else '') + jid + '.mp4')
    temporary = directory / 'tmp' / jid; temporary.mkdir(parents=True, exist_ok=True)
    try:
        value = metadata(directory); src = directory / value['source']
        # Conservative output estimate; monitoring the actual free space continues during encoding.
        ensure_space(int((req.end - req.start) * 2_000_000))
        update_job(jid, status='rendering')
        vf = []
        width, height = (360, 640) if req.preview else (1080, 1920)
        if req.vertical:
            if req.framing == 'center':
                vf.append(f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1')
            else:
                # Fit preserves every face without making unverified speaker-tracking claims.
                vf.append(f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
        elif req.preview:
            vf.append('scale=640:-2')
        caption_count = 0
        if req.captions:
            if not diagnostics(DATA).get('subtitles'):
                raise ValueError('This FFmpeg lacks the subtitles filter. Install a build with libass.')
            srt, timings = captions_for(value.get('transcript') or [], req.start, req.end)
            if not timings:
                raise ValueError('No transcript overlaps this clip. Transcribe or edit its transcript first.')
            caption_count = len(timings)
            (temporary / 'captions.srt').write_text(srt, encoding='utf-8')
            vf.append("subtitles=captions.srt:force_style='FontSize=" + str(req.caption_font_size) +
                      ',PrimaryColour=' + req.caption_color + ",Outline=2,Alignment=2,MarginV=90'")
        cmd = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', str(req.start), '-i', str(src),
               '-t', str(req.end - req.start), '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn',
               '-threads', '2', '-filter_threads', '1']
        if vf:
            cmd += ['-vf', ','.join(vf)]
        if req.encoder == 'hardware':
            from platform import system
            if system() != 'Darwin' or not diagnostics(DATA).get('videotoolbox_available'):
                raise ValueError('VideoToolbox is unavailable. Select software encoding.')
            cmd += ['-c:v', 'h264_videotoolbox', '-b:v', '6M']
        else:
            cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21']
        cmd += ['-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(out)]
        # File-backed stderr avoids a deadlocked pipe and unbounded RAM for long videos.
        with (temporary / 'render.log').open('w+') as log:
            proc = subprocess.Popen(cmd, cwd=temporary, stdout=subprocess.DEVNULL, stderr=log)
            try:
                while proc.poll() is None:
                    ensure_space(); time.sleep(.25)
            except BaseException:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                raise
            if proc.returncode:
                log.seek(0, 2); length = log.tell(); log.seek(max(0, length-2500))
                raise RuntimeError(log.read())
        update_job(jid, status='validating')
        qa = validate_export(out, req.end-req.start, req.vertical,
                             any(s['codec_type'] == 'audio' for s in probe(src)['streams']), dimensions=(width, height))
        qa.update(caption_cues=caption_count, framing=req.framing,
                  limitations='No semantic, face tracking, perceptual sync or editorial guarantee')
        update_job(jid, status='done', url=f'/api/download/{pid}/{jid}', filename=out.name, preview=req.preview, quality_checks=qa)
    except Exception as exc:
        out.unlink(missing_ok=True)
        update_job(jid, status='paused' if isinstance(exc, OSError) else 'error', error=str(exc))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


@app.post('/api/projects/{pid}/render')
def render(pid: str, req: ClipRequest):
    directory = folder(pid); value = metadata(directory)
    if not value['source']: raise HTTPException(409, 'Upload a local source to this project first')
    if not req.start < req.end <= value['duration'] + .05:
        raise HTTPException(400, 'Invalid clip boundaries')
    jid = uuid.uuid4().hex
    with LOCK:
        if DB.active(pid, 'render'):
            raise HTTPException(409, 'A render is already queued for this project')
        DB.create_job(jid, pid, 'render', {'status': 'queued'})
    WORKERS.submit(render_worker, pid, jid, req)
    return {'job_id': jid}


@app.get('/api/jobs/{jid}')
def job(jid: str):
    value = DB.job(jid)
    if value is None:
        raise HTTPException(404, 'Job not found')
    return value


@app.get('/api/download/{pid}/{jid}')
def download(pid: str, jid: str):
    if not re.fullmatch(r'[a-f0-9]{32}', jid):
        raise HTTPException(400, 'Invalid export ID')
    directory = folder(pid)
    state = DB.job(jid)
    path = directory / (('preview-' if state and state.get('preview') else '') + jid + '.mp4')
    if not state or state['status'] != 'done' or not path.exists():
        raise HTTPException(404, 'Validated export not found')
    return FileResponse(path, filename='clipforge-' + jid[:8] + '.mp4', media_type='video/mp4')


class AnalyzeRequest(BaseModel):
    mode: Literal['fast', 'balanced', 'quality'] = 'balanced'
    allow_download: bool = False


def transcribe_worker(pid, jid, req):
    directory = folder(pid); scratch = directory / 'tmp' / jid
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        value = metadata(directory)
        if not any(s['codec_type'] == 'audio' for s in probe(directory / value['source'])['streams']):
            raise ValueError('This source has no audio to transcribe')
        transcript = transcribe(directory / value['source'], value['duration'], req.mode,
                                req.allow_download, MODELS, scratch, DB,
                                lambda **changes: update_job(jid, **changes), ensure_space)
        update_job(jid, status='analyzing')
        suggestions = rank_candidates(transcript, DB.preferences())
        patch_meta(directory, transcript=transcript, suggestions=suggestions, analysis_mode=req.mode)
        update_job(jid, status='done', count=len(transcript), ranking='heuristic')
    except ImportError:
        update_job(jid, status='error', error='Optional AI packages are missing. Run Enable AI.command, then retry.')
    except Exception as exc:
        update_job(jid, status='paused' if isinstance(exc, OSError) else 'error', error=str(exc))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@app.post('/api/projects/{pid}/analyze')
def analyze(pid: str, req: AnalyzeRequest = AnalyzeRequest()):
    folder(pid); jid = uuid.uuid4().hex
    with LOCK:
        existing = DB.active(pid, 'analysis')
        if existing:
            return {'job_id': existing}
        DB.create_job(jid, pid, 'analysis', {'status': 'queued'})
    WORKERS.submit(transcribe_worker, pid, jid, req)
    return {'job_id': jid}


class Segment(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=10000)


class TranscriptRequest(BaseModel):
    segments: list[Segment]


@app.put('/api/projects/{pid}/transcript')
def edit_transcript(pid: str, req: TranscriptRequest):
    directory = folder(pid); value = metadata(directory)
    segments = [s.model_dump() for s in req.segments]
    previous = 0
    for segment in segments:
        if not previous <= segment['start'] < segment['end'] <= value['duration']:
            raise HTTPException(400, 'Transcript must be ordered, non-overlapping and within source duration')
        previous = segment['end']
    return patch_meta(directory, transcript=segments, suggestions=rank_candidates(segments, DB.preferences()))


@app.put('/api/projects/{pid}/edits')
def save_edits(pid: str, req: ClipRequest):
    directory = folder(pid); value = metadata(directory)
    if not value['source']: raise HTTPException(409, 'Upload a local source to this project first')
    if not req.start < req.end <= value['duration']:
        raise HTTPException(400, 'Invalid edit boundaries')
    return patch_meta(directory, edits=req.model_dump())


class FeedbackRequest(BaseModel):
    candidate_id: str
    rating: Literal[-1, 1]


@app.post('/api/projects/{pid}/feedback')
def feedback(pid: str, req: FeedbackRequest):
    directory = folder(pid); value = metadata(directory)
    candidate = next((c for c in value['suggestions'] if c['id'] == req.candidate_id), None)
    if not candidate:
        raise HTTPException(404, 'Candidate not found')
    DB.feedback(pid, candidate['id'], req.rating, candidate['features'])
    return patch_meta(directory, suggestions=rank_candidates(value['transcript'], DB.preferences()))


@app.get('/api/models')
def models():
    return model_inventory(MODELS)


@app.delete('/api/models/{name}')
def delete_model(name: str):
    if name not in {c['model'] for c in MODES.values()}:
        raise HTTPException(400, 'Unsupported model')
    # Do not remove models while an analysis job could be reading/downloading them.
    with LOCK:
        if any(DB.active(p['id'], 'analysis') for p in projects()):
            raise HTTPException(409, 'Wait for analysis to finish before removing a model')
        shutil.rmtree(model_path(MODELS, name), ignore_errors=True)
    return {'removed': name}


@app.get('/api/storage')
def storage():
    totals = {'original_media': 0, 'ai_models': 0, 'temporary': 0, 'previews': 0, 'exports': 0, 'metadata_and_cache': 0}
    for path in DATA.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        if MODELS in path.parents: category = 'ai_models'
        elif 'tmp' in path.relative_to(DATA).parts: category = 'temporary'
        elif path.name.startswith('source'): category = 'original_media'
        elif path.name.startswith('preview-'): category = 'previews'
        elif path.suffix == '.mp4': category = 'exports'
        else: category = 'metadata_and_cache'
        totals[category] += path.stat().st_size
    return {'bytes': totals, 'free_bytes': shutil.disk_usage(DATA).free,
            'reserve_bytes': DB.setting('storage_reserve_bytes', RESERVE), 'location': str(DATA),
            'policy': 'Only transient working files are removed automatically. Originals and exports are preserved.'}


class StorageSettings(BaseModel):
    reserve_bytes: int = Field(ge=64*1024*1024)


@app.put('/api/storage/settings')
def storage_settings(req: StorageSettings):
    DB.set_setting('storage_reserve_bytes', req.reserve_bytes)
    return storage()


@app.get('/api/presets')
def presets():
    return {**PRESETS, **DB.setting('presets', {})}


@app.put('/api/presets/{name}')
def save_preset(name: str, req: ClipRequest):
    if not 1 <= len(name) <= 80:
        raise HTTPException(400, 'Preset name must contain 1–80 characters')
    with LOCK:
        value = DB.setting('presets', {}); value[name] = req.model_dump(exclude={'start', 'end', 'title', 'preview'})
        DB.set_setting('presets', value)
    return presets()


class ImportRequest(BaseModel):
    url: str = Field(max_length=4096)


def import_worker(pid, jid, url):
    from imports import download_media, validate_url
    directory = folder(pid); destination = directory / 'source.mp4'
    try:
        update_job(jid, status='importing')
        parsed = validate_url(url)
        if parsed.hostname.lower() in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
            raise ValueError('YouTube extraction is not installed. Use an authorized downloaded copy and upload it locally. No access controls are bypassed.')
        download_media(url, destination, ensure_space)
        info = probe(destination)
        if not any(s['codec_type'] == 'video' for s in info['streams']):
            raise ValueError('Downloaded file has no video stream')
        from analysis import fingerprint
        patch_meta(directory, source=destination.name, duration=info['duration'], source_hash=fingerprint(destination), import_error=None)
        update_job(jid, status='done')
    except Exception as exc:
        destination.unlink(missing_ok=True)
        patch_meta(directory, import_error=str(exc))
        update_job(jid, status='error', error=str(exc), alternative='Upload an authorized local video. This project has been preserved.')


@app.post('/api/import')
def import_url(req: ImportRequest):
    pid = uuid.uuid4().hex; jid = uuid.uuid4().hex
    directory = DATA / pid; directory.mkdir()
    save_meta(directory, {'id': pid, 'name': 'URL import', 'source': None, 'duration': 0,
                          'transcript': None, 'suggestions': [], 'edits': {}})
    DB.create_job(jid, pid, 'import', {'status': 'queued'})
    WORKERS.submit(import_worker, pid, jid, req.url)
    return {'id': pid, 'job_id': jid}


@app.post('/api/projects/{pid}/replace-source')
def replace_source(pid: str, file: UploadFile = File(...)):
    directory = folder(pid)
    if metadata(directory)['source'] is not None:
        raise HTTPException(409, 'A source already exists. Upload as a new project to preserve it.')
    imported = upload(file)
    new = DATA / imported['id']
    try:
        shutil.move(str(new / imported['source']), str(directory / imported['source']))
        imported['id'] = pid
        save_meta(directory, imported)
    finally:
        shutil.rmtree(new, ignore_errors=True)
    return imported


@app.get('/api/projects/{pid}/jobs')
def project_jobs(pid: str):
    folder(pid)
    return DB.project_jobs(pid)
