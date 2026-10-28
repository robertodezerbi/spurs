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

from runtime import executable, run, media_info, validate_export, diagnostics, regular_files
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
    framing: Literal['fit', 'center', 'smart'] = 'fit'
    captions: bool = False
    preview: bool = False
    caption_font_size: int = Field(default=18, ge=12, le=32)
    caption_color: str = Field(default='&H00FFFFFF', pattern=r'^&H[0-9A-Fa-f]{8}$')
    caption_font: Literal['Arial','Helvetica','DejaVu Sans'] = 'Arial'
    caption_highlight: str = Field(default='&H0000D7FF', pattern=r'^&H[0-9A-Fa-f]{8}$')
    caption_animation: Literal['none','fade','karaoke'] = 'none'
    caption_position: Literal['bottom','center','top'] = 'bottom'
    normalize_audio: bool = False
    denoise_audio: bool = False
    fade_audio: bool = False
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
        vision_report = None
        if req.vertical and req.framing == 'smart':
            try:
                from vision import analyze_video, tracking_filter
            except ImportError as exc:
                raise ValueError('Vision dependencies are missing. Install requirements-vision.txt, then retry.') from exc
            key = f'vision-mouth-v1:{value.get("source_hash")}:{req.start}:{req.end}'
            vision_report = DB.cache_get(key)
            if vision_report is None:
                update_job(jid, status='tracking faces')
                vision_report = analyze_video(src, req.start, req.end, lambda **kw: update_job(jid, **kw))
                DB.cache_put(key, vision_report)
            tracking = tracking_filter(vision_report, temporary, width, height)
            if tracking: vf.append(tracking)
        if req.vertical:
            if req.framing == 'smart' and vf:
                pass
            elif req.framing == 'center':
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
            from captions import ass_captions
            source_video=next(s for s in probe(src)['streams'] if s['codec_type']=='video')
            canvas=(1080,1920) if req.vertical else (1080,round(1080*source_video['height']/source_video['width']))
            script, caption_count, caption_timing = ass_captions(value.get('transcript') or [], req.start, req.end,
                font=req.caption_font,size=req.caption_font_size,color=req.caption_color,
                highlight=req.caption_highlight,animation=req.caption_animation,position=req.caption_position,
                canvas=canvas)
            (temporary / 'captions.ass').write_text(script,encoding='utf-8')
            vf.append('subtitles=captions.ass')
        has_audio=any(s['codec_type']=='audio' for s in probe(src)['streams'])
        audio_report={'source_audio':has_audio}
        af=[]
        if has_audio:
            from audio import audio_filters
            update_job(jid,status='preparing audio')
            af,audio_report=audio_filters(src,req.start,req.end,req.normalize_audio,req.denoise_audio,req.fade_audio)
        cmd = [executable('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-ss', str(req.start), '-i', str(src),
               '-t', str(req.end - req.start), '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn',
               '-threads', '2', '-filter_threads', '1']
        if vf:
            cmd += ['-vf', ','.join(vf)]
        if af: cmd += ['-af', ','.join(af)]
        if req.encoder == 'hardware':
            from platform import system
            if system() != 'Darwin' or not diagnostics(DATA).get('videotoolbox_available'):
                raise ValueError('VideoToolbox is unavailable. Select software encoding.')
            cmd += ['-c:v', 'h264_videotoolbox', '-b:v', '6M']
        else:
            cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21']
        cmd += ['-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar','48000','-ac','2','-b:a', '160k', '-movflags', '+faststart', str(out)]
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
        qa.update(caption_cues=caption_count, framing=req.framing, audio_processing=audio_report,
                  caption_timing=caption_timing if req.captions else None, caption_animation=req.caption_animation,
                  tracking={k:v for k,v in vision_report.items() if k!='points'} if vision_report else None,
                  limitations='No perceptual sync, speaker-identity or editorial guarantee; review smart tracking manually')
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
        patch_meta(directory, transcript=transcript, suggestions=[], analysis_mode=req.mode, semantic_summary=None, ranking=None)
        update_job(jid, status='done', count=len(transcript), next_step='Run semantic review with an installed local model, or explicitly choose heuristic discovery')
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
    if DB.active(pid,'analysis') or DB.active(pid,'semantic'):raise HTTPException(409,'Wait for transcript/semantic analysis to finish before editing the transcript')
    directory = folder(pid); value = metadata(directory)
    segments = [s.model_dump() for s in req.segments]
    previous = 0
    for segment in segments:
        if not previous <= segment['start'] < segment['end'] <= value['duration']:
            raise HTTPException(400, 'Transcript must be ordered, non-overlapping and within source duration')
        previous = segment['end']
    return patch_meta(directory, transcript=segments, suggestions=[], semantic_summary=None, ranking=None)


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
    if candidate.get('ranking') == 'semantic-local':
        weights = DB.preferences()
        for item in value['suggestions']:
            item['score'] = round(sum(v*(1/3+weights.get(k,0)) for k,v in item['features'].items()),3)
        return patch_meta(directory, suggestions=sorted(value['suggestions'],key=lambda c:c['score'],reverse=True))
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
    for path,information in regular_files(DATA):
        if MODELS in path.parents: category = 'ai_models'
        elif 'tmp' in path.relative_to(DATA).parts: category = 'temporary'
        elif 'previews' in path.relative_to(DATA).parts: category = 'previews'
        elif path.name.startswith('source'): category = 'original_media'
        elif path.name.startswith('preview-'): category = 'previews'
        elif path.suffix == '.mp4': category = 'exports'
        else: category = 'metadata_and_cache'
        totals[category] += information.st_size
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


class SemanticRequest(BaseModel):
    model: str = Field(min_length=1, max_length=120)


@app.get('/api/semantic/models')
def semantic_models():
    from semantic import installed_models
    try: return {'available': True, 'models': installed_models()}
    except RuntimeError as exc: return {'available': False, 'models': [], 'reason': str(exc)}


def semantic_worker(pid, jid, model):
    from semantic import semantic_rank
    try:
        directory = folder(pid); value = metadata(directory)
        result = semantic_rank(value.get('transcript') or [], model, DB,
                               lambda **kw: update_job(jid, **kw), DB.preferences())
        patch_meta(directory, suggestions=result['suggestions'], semantic_summary=result['summary'], ranking='semantic-local')
        update_job(jid, status='done', count=len(result['suggestions']), model=model)
    except Exception as exc: update_job(jid, status='error', error=str(exc))


@app.post('/api/projects/{pid}/semantic')
def semantic_analysis(pid: str, req: SemanticRequest):
    from semantic import installed_models,verify_local_model
    value = metadata(folder(pid))
    if not value.get('transcript'): raise HTTPException(409, 'A transcript is required first')
    try:
        if req.model not in {m['name'] for m in installed_models()}:
            raise HTTPException(400, 'Select an installed local model. No model is downloaded automatically.')
        verify_local_model(req.model)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(503, str(exc)) from exc
    jid = uuid.uuid4().hex
    with LOCK:
        if DB.active(pid, 'semantic'): raise HTTPException(409, 'Semantic analysis is already running')
        DB.create_job(jid, pid, 'semantic', {'status': 'queued'})
    WORKERS.submit(semantic_worker, pid, jid, req.model)
    return {'job_id': jid}


class TimelineClip(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str = Field(default='Clip', max_length=120)


class TimelineRequest(BaseModel):
    clips: list[TimelineClip] = Field(max_length=200)


def validate_timeline(pid, clips):
    value=metadata(folder(pid)); ids=set()
    for clip in clips:
        if clip.id in ids or not clip.start < clip.end <= value['duration']:
            raise HTTPException(400,'Timeline clips require unique IDs and valid source boundaries')
        ids.add(clip.id)
    return value


@app.put('/api/projects/{pid}/timeline')
def save_timeline(pid: str, req: TimelineRequest):
    validate_timeline(pid,req.clips)
    return patch_meta(folder(pid),timeline={'version':1,'clips':[c.model_dump() for c in req.clips]})


class TimelineRenderRequest(ClipRequest):
    clips: list[TimelineClip] = Field(min_length=1,max_length=200)


def timeline_render_worker(pid,jid,req):
    directory=folder(pid); temporary=directory/'tmp'/jid; temporary.mkdir(parents=True,exist_ok=True)
    parts=[]; out=directory/(('preview-' if req.preview else '')+jid+'.mp4')
    try:
        duration=sum(c.end-c.start for c in req.clips)
        ensure_space(int(duration*2_000_000))
        for index,clip in enumerate(req.clips):
            update_job(jid,status='rendering timeline',progress=f'Clip {index+1}/{len(req.clips)}')
            child=uuid.uuid4().hex
            DB.create_job(child,pid,'timeline_part',{'status':'queued'})
            request=ClipRequest(**{**req.model_dump(exclude={'clips'}),'start':clip.start,'end':clip.end})
            render_worker(pid,child,request)
            state=DB.job(child)
            if state['status']!='done':
                if state['status']=='paused': raise OSError(state.get('error','Timeline render paused'))
                raise RuntimeError(state.get('error','Timeline clip failed'))
            part=directory/state['filename']; parts.append(part)
            os.link(part,temporary/f'part-{index}.mp4')
        (temporary/'concat.txt').write_text('\n'.join(f"file 'part-{i}.mp4'" for i in range(len(parts))))
        update_job(jid,status='assembling timeline')
        has_audio=any(s['codec_type']=='audio' for s in probe(directory/metadata(directory)['source'])['streams'])
        cmd=[executable('ffmpeg'),'-nostdin','-v','error','-y','-f','concat','-safe','0','-i','concat.txt',
             '-threads','2','-filter_threads','1','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p']
        if has_audio: cmd+=['-af','aresample=async=1:first_pts=0','-c:a','aac','-ar','48000','-ac','2']
        cmd+=['-movflags','+faststart',str(out)]
        with (temporary/'concat.log').open('w+') as log:
            process=subprocess.Popen(cmd,cwd=temporary,stderr=log,stdout=subprocess.DEVNULL)
            try:
                while process.poll() is None: ensure_space(); time.sleep(.2)
            except BaseException:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
                raise
            if process.returncode:
                log.seek(0,2); length=log.tell();log.seek(max(0,length-2000));raise RuntimeError(log.read())
        qa=validate_export(out,duration,req.vertical,has_audio,dimensions=(360,640) if req.preview else (1080,1920))
        qa.update(timeline_clips=len(parts),source_ranges=[{'start':c.start,'end':c.end} for c in req.clips])
        update_job(jid,status='done',url=f'/api/download/{pid}/{jid}',filename=out.name,preview=req.preview,quality_checks=qa)
    except Exception as exc:
        out.unlink(missing_ok=True)
        update_job(jid,status='paused' if isinstance(exc,OSError) else 'error',error=str(exc))
    finally:
        for part in parts: part.unlink(missing_ok=True)
        shutil.rmtree(temporary,ignore_errors=True)


@app.post('/api/projects/{pid}/timeline/render')
def render_timeline(pid: str, req: TimelineRenderRequest):
    validate_timeline(pid,req.clips); jid=uuid.uuid4().hex
    with LOCK:
        if DB.active(pid,'render'): raise HTTPException(409,'A render is already running')
        DB.create_job(jid,pid,'render',{'status':'queued'})
    WORKERS.submit(timeline_render_worker,pid,jid,req)
    return {'job_id':jid}


def waveform_worker(pid,jid):
    try:
        from waveform import envelope
        directory=folder(pid);value=metadata(directory)
        key='waveform-v1:'+value['source_hash']
        waveform=DB.cache_get(key)
        if waveform is None:
            if not any(s['codec_type']=='audio' for s in probe(directory/value['source'])['streams']):
                raise ValueError('Source has no audio stream')
            update_job(jid,status='decoding waveform')
            waveform=envelope(directory/value['source'],value['duration'])
            DB.cache_put(key,waveform)
        patch_meta(directory,waveform=waveform)
        update_job(jid,status='done',waveform=waveform)
    except Exception as exc:update_job(jid,status='error',error=str(exc))


@app.post('/api/projects/{pid}/waveform')
def build_waveform(pid: str):
    value=metadata(folder(pid))
    if not value.get('source'): raise HTTPException(409,'A local source is required')
    jid=uuid.uuid4().hex
    with LOCK:
        active=DB.active(pid,'waveform')
        if active:return {'job_id':active}
        DB.create_job(jid,pid,'waveform',{'status':'queued'})
    WORKERS.submit(waveform_worker,pid,jid)
    return {'job_id':jid}


THUMBNAIL_LOCK=threading.Semaphore(2)


@app.get('/api/projects/{pid}/thumbnail')
def thumbnail(pid: str,time: float=0):
    directory=folder(pid);value=metadata(directory)
    if not math.isfinite(time) or not 0<=time<value['duration']:raise HTTPException(400,'Invalid thumbnail time')
    previews=directory/'previews';previews.mkdir(exist_ok=True)
    stamp=round(time*100);destination=previews/f'thumb-{stamp}.jpg'
    with THUMBNAIL_LOCK:
        if not destination.exists():
            ensure_space(2*1024*1024)
            temporary=previews/(uuid.uuid4().hex+'.jpg')
            try:
                run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(stamp/100),'-i',str(directory/value['source']),
                     '-frames:v','1','-vf','scale=160:-2','-threads','1','-q:v','4',str(temporary)],timeout=30)
                if not temporary.exists():raise ValueError('No video frame at this time')
                temporary.replace(destination)
            except Exception as exc:
                temporary.unlink(missing_ok=True);raise HTTPException(400,str(exc)) from exc
    return FileResponse(destination,media_type='image/jpeg')


@app.post('/api/projects/{pid}/heuristic')
def heuristic_discovery(pid: str):
    directory=folder(pid);value=metadata(directory)
    if not value.get('transcript'):raise HTTPException(409,'A transcript is required first')
    return patch_meta(directory,suggestions=rank_candidates(value['transcript'],DB.preferences()),ranking='heuristic',semantic_summary=None)
