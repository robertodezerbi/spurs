import json, os, re, shutil, subprocess, threading, uuid
from pathlib import Path
from runtime import executable, run, validate_export, diagnostics
from concurrent.futures import ThreadPoolExecutor
import math
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv('CLIPFORGE_DATA_DIR', str(ROOT/'data'))).expanduser().resolve(); DATA.mkdir(parents=True,exist_ok=True)
WORKERS=ThreadPoolExecutor(max_workers=1,thread_name_prefix='clipforge')
app=FastAPI(title='ClipForge — Local Video Clipper')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
JOBS={}

def probe(path):
    info=json.loads(run([executable('ffprobe'),'-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)]))
    return {'duration':float(info['format'].get('duration',0)), 'streams':info.get('streams',[])}

def folder(pid):
    if not re.fullmatch(r'[a-f0-9]{32}',pid): raise HTTPException(400,'Invalid project ID')
    p=DATA/pid
    if not p.is_dir(): raise HTTPException(404,'Project not found')
    return p

def metadata(p): return json.loads((p/'project.json').read_text())

def save_meta(p,m):
    temporary=p/('meta-'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(m,indent=2))
    temporary.replace(p/'project.json')

@app.get('/api/health')
def health(): return {'application':'clipforge','status':'ok'}

@app.get('/api/diagnostics')
def diagnose(): return diagnostics(DATA)

@app.get('/')
def home(): return FileResponse(ROOT/'static'/'index.html')

@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    pid=uuid.uuid4().hex; p=DATA/pid;p.mkdir()
    suffix=Path(file.filename or 'video.mp4').suffix.lower()
    if suffix not in ('.mp4','.mov','.mkv','.webm','.avi','.m4v'):
        shutil.rmtree(p);raise HTTPException(400,'Unsupported video format')
    dest=p/('source'+suffix)
    try:
        with dest.open('wb') as f:
            while chunk:=await file.read(4*1024*1024): f.write(chunk)
        info=probe(dest)
        if not any(s.get('codec_type')=='video' for s in info['streams']): raise ValueError('File has no video stream')
        m={'id':pid,'name':Path(file.filename).name,'source':dest.name,'duration':info['duration'],'transcript':None,'suggestions':[]}
        save_meta(p,m)
        return m
    except Exception as e:
        shutil.rmtree(p,ignore_errors=True);raise HTTPException(400,str(e))

@app.get('/api/projects')
def projects():
    out=[]
    for p in DATA.iterdir():
        if (p/'project.json').exists():
            try: out.append(metadata(p))
            except Exception: pass
    return out

@app.get('/api/projects/{pid}')
def project(pid:str): return metadata(folder(pid))

@app.get('/api/projects/{pid}/source')
def source(pid:str):
    p=folder(pid);m=metadata(p)
    return FileResponse(p/m['source'],media_type='video/mp4')

class ClipRequest(BaseModel):
    start:float
    end:float
    vertical:bool=True
    captions:bool=False
    title:str='clip'

def srt_time(s):
    ms=round(s*1000);h,ms=divmod(ms,3600000);mi,ms=divmod(ms,60000);sec,ms=divmod(ms,1000)
    return f'{h:02}:{mi:02}:{sec:02},{ms:03}'

def render_worker(pid,jobid,req):
    job=JOBS[jobid];out=None
    try:
        p=folder(pid);m=metadata(p)
        job.update(status='rendering')
        src=p/m['source'];out=p/(jobid+'.mp4')
        vf=[]
        if req.vertical: vf.append('scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1')
        if req.captions:
            if not m.get('transcript'): raise ValueError('Captions requested but no transcript is available. Analyze the video first.')
            transcript=m.get('transcript') or []
            lines=[];i=0
            for seg in transcript:
                a=max(req.start,float(seg['start']));b=min(req.end,float(seg['end']))
                if b<=a:continue
                i+=1;lines.extend([str(i),f'{srt_time(a-req.start)} --> {srt_time(b-req.start)}',seg['text'].strip(),''])
            if lines:
                srt=p/(jobid+'.srt');srt.write_text('\n'.join(lines))
                # Use relative filename from project cwd, avoiding path escaping issues
                vf.append(f"subtitles={jobid}.srt:force_style='FontSize=14,Outline=2,Alignment=2,MarginV=140'")
        cmd=[executable('ffmpeg'),'-y','-ss',str(req.start),'-i',str(src),'-t',str(req.end-req.start)]
        if vf:cmd+=['-vf',','.join(vf)]
        cmd+=['-threads','2','-filter_threads','1','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)]
        proc=subprocess.run(cmd,cwd=p,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if proc.returncode:raise RuntimeError(proc.stderr[-1800:])
        qa=validate_export(out,req.end-req.start,req.vertical,any(s['codec_type']=='audio' for s in probe(src)['streams']))
        job.update(quality_checks=qa)
        job.update(status='done',url=f'/api/download/{pid}/{jobid}',filename=out.name)
    except Exception as e:
        if out: out.unlink(missing_ok=True)
        job.update(status='error',error=str(e))

@app.post('/api/projects/{pid}/render')
def render(pid:str,req:ClipRequest):
    p=folder(pid);m=metadata(p)
    if not (math.isfinite(req.start) and math.isfinite(req.end)):raise HTTPException(400,'Clip times must be finite')
    if not (0<=req.start<req.end<=m['duration']+.05):raise HTTPException(400,'Invalid clip boundaries')
    jobid=uuid.uuid4().hex;JOBS[jobid]={'status':'queued'}
    WORKERS.submit(render_worker,pid,jobid,req)
    return {'job_id':jobid}

@app.get('/api/jobs/{jobid}')
def job(jobid:str):
    if jobid not in JOBS:raise HTTPException(404,'Job not found')
    return JOBS[jobid]

@app.get('/api/download/{pid}/{jobid}')
def download(pid:str,jobid:str):
    if not re.fullmatch(r'[a-f0-9]{32}',jobid):raise HTTPException(400,'Invalid export ID')
    p=folder(pid);f=p/(jobid+'.mp4')
    if not f.exists():raise HTTPException(404,'Export not found')
    return FileResponse(f,filename='clipforge-'+jobid[:8]+'.mp4',media_type='video/mp4')

def transcribe_worker(pid,jobid):
    p=folder(pid);m=metadata(p);j=JOBS[jobid]
    try:
        j.update(status='loading AI model (first run may download weights)')
        from faster_whisper import WhisperModel
        model=WhisperModel(os.getenv('WHISPER_MODEL','base'),device='cpu',compute_type='int8')
        j.update(status='transcribing')
        segments,_=model.transcribe(str(p/m['source']),vad_filter=True)
        transcript=[{'start':round(s.start,2),'end':round(s.end,2),'text':s.text.strip()} for s in segments]
        m['transcript']=transcript
        # Transparent heuristic suggestions: contiguous speech windows ranked by density and natural boundaries.
        candidates=[];target=40
        for i,seg in enumerate(transcript):
            start=seg['start'];end=start;parts=[]
            for nxt in transcript[i:]:
                if nxt['end']-start>65:break
                end=nxt['end'];parts.append(nxt['text'])
                dur=end-start
                if 22<=dur<=55:
                    words=len(' '.join(parts).split());density=words/max(dur,1)
                    score=round(50+min(25,density*7)-abs(dur-target)*.35,1)
                    candidates.append({'start':round(start,2),'end':round(end,2),'score':score,'text':' '.join(parts)[:230]})
                    if dur>=target:break
        candidates.sort(key=lambda c:c['score'],reverse=True)
        selected=[]
        for c in candidates:
            if all(min(c['end'],v['end'])-max(c['start'],v['start'])<10 for v in selected):selected.append(c)
            if len(selected)>=8:break
        m['suggestions']=selected;save_meta(p,m)
        j.update(status='done',count=len(transcript))
    except ImportError:j.update(status='error',error='Install optional AI dependency: pip install -r requirements-ai.txt')
    except Exception as e:j.update(status='error',error=str(e))

@app.post('/api/projects/{pid}/analyze')
def analyze(pid:str):
    folder(pid);jid=uuid.uuid4().hex;JOBS[jid]={'status':'queued'}
    WORKERS.submit(transcribe_worker,pid,jid)
    return {'job_id':jid}
